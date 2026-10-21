import tempfile
import unittest
from unittest.mock import patch

from espbs.archive import export_batch, verify_archive
from espbs.archive_queue import run, start, stop, status, initialize, change
from espbs.disk import LowDiskSpace
from espbs.jobs import Job, worker_lock
from espbs.partitions import summary
from espbs.retention import cleanup, confirm_copy
from espbs.storage import Batch


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Job.create(self.temp.name, 60)
        self.batch = Batch(self.temp.name, self.job.id)
        for i in range(60):
            self.batch.add({'source': 'synthetic', 'source_url': f'https://fixture.example/{i}',
                            'name': f'Synthetic {i}'})
        with self.job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")

    def release_first(self):
        with self.job.db() as db:
            child_id = db.execute('SELECT child_id FROM archive_parts ORDER BY seq LIMIT 1').fetchone()[0]
        child = Job(self.job.root, child_id)
        path = self.job.root / 'exports' / (child.id + '.zip')
        confirm_copy(child, verify_archive(path))
        cleanup(child, child.id)

    def test_window_pause_then_explicit_release_and_resume(self):
        original = list(self.batch.records())
        value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'WAITING_DOWNLOAD')
        self.assertEqual(value['last_seq'], 2)
        self.assertEqual(summary(self.job)['count'], 2)
        self.assertEqual(run(self.job.root, self.job.id)['state'], 'WAITING_DOWNLOAD')
        self.assertEqual(summary(self.job)['count'], 2)
        self.release_first()
        value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'COMPLETED')
        self.assertEqual(value['last_seq'], 3)
        self.assertEqual(value['release_seq'], 1)
        self.assertEqual(original, list(self.batch.records()))

    def test_disk_pause_keeps_cursor_and_does_not_create_part(self):
        with patch('espbs.archive_queue.require_space', side_effect=LowDiskSpace('synthetic disk full')):
            value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'PAUSED_DISK')
        self.assertEqual(value['last_seq'], 0)
        self.assertEqual(summary(self.job)['count'], 0)
        self.assertEqual(run(self.job.root, self.job.id)['state'], 'WAITING_DOWNLOAD')

    def test_prepare_failure_retries_same_child(self):
        with patch('espbs.export_tasks.run', side_effect=ValueError('synthetic failure')):
            value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'FAILED')
        child_id = value['current_child']
        self.assertEqual(value['last_seq'], 0)
        value = run(self.job.root, self.job.id)
        self.assertEqual(value['last_seq'], 2)
        with self.job.db() as db:
            self.assertEqual(db.execute('SELECT child_id FROM archive_parts WHERE seq=1').fetchone()[0], child_id)

    def test_stop_after_current_part_and_resume_cursor(self):
        from espbs.export_tasks import run as prepare
        def prepare_and_stop(*args):
            result = prepare(*args)
            stop(self.job)
            return result
        with patch('espbs.export_tasks.run', side_effect=prepare_and_stop):
            value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'STOPPED')
        self.assertEqual(value['last_seq'], 1)
        with patch('espbs.archive_queue.subprocess.Popen'):
            start(self.job)
        self.assertEqual(run(self.job.root, self.job.id)['last_seq'], 2)

    def test_existing_completed_archive_is_not_downloaded_again_after_crash(self):
        from espbs.export_tasks import run as prepare
        def publish_then_fail(*args):
            prepare(*args)
            raise ValueError('synthetic crash after publish')
        with patch('espbs.export_tasks.run', side_effect=publish_then_fail):
            value = run(self.job.root, self.job.id)
        self.assertEqual(value['last_seq'], 0)
        first = value['current_child']
        def check_not_first(root, child_id):
            self.assertNotEqual(child_id, first)
            return prepare(root, child_id)
        with patch('espbs.export_tasks.run', side_effect=check_not_first):
            self.assertEqual(run(self.job.root, self.job.id)['last_seq'], 2)

    def test_partial_report_pauses_for_review(self):
        self.batch.add({'source': 'synthetic', 'source_url': 'https://fixture.example/partial',
                        'name': 'Synthetic incomplete', 'documents': [{'url': 'https://external.example/doc.pdf'}]})
        # One large partition ensures the skipped fixture appears in the first archive.
        with patch('espbs.partitions.MAX_PRODUCTS', 100):
            value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'REVIEW')
        self.assertEqual(value['incomplete_parts'], 1)
        self.assertEqual(value['last_seq'], 1)
        with patch('espbs.archive_queue.subprocess.Popen'):
            start(self.job)
        self.assertEqual(run(self.job.root, self.job.id)['state'], 'COMPLETED')
        self.assertEqual(status(self.job)['incomplete_parts'], 1)

    def test_launch_duplicate_and_stale_process(self):
        with patch('espbs.archive_queue.subprocess.Popen') as popen:
            self.assertEqual(start(self.job)['state'], 'QUEUED')
            self.assertEqual(start(self.job)['state'], 'QUEUED')
            self.assertEqual(popen.call_count, 1)
        with self.job.db() as db:
            db.execute('UPDATE archive_queue SET updated=0')
        with worker_lock(self.job.path.with_suffix('.archive-queue-worker.lock')):
            self.assertEqual(status(self.job)['state'], 'QUEUED')
        self.assertEqual(status(self.job)['state'], 'FAILED')

    def test_active_queue_blocks_parent_cleanup(self):
        path = export_batch(self.batch, self.job.root / 'exports')
        confirm_copy(self.job, verify_archive(path))
        initialize(self.job)
        change(self.job, 'QUEUED')
        with self.assertRaisesRegex(ValueError, 'очередь'):
            cleanup(self.job, self.job.id)
        self.assertEqual(self.batch.info()['record_count'], 60)

    def test_wrong_valid_zip_cannot_advance_queue(self):
        from espbs.export_tasks import run as prepare
        def publish_then_fail(*args):
            prepare(*args)
            raise ValueError('synthetic interruption')
        with patch('espbs.export_tasks.run', side_effect=publish_then_fail):
            value = run(self.job.root, self.job.id)
        target = self.job.root / 'exports' / (value['current_child'] + '.zip')
        other = Batch.create(self.job.root)
        other.add({'source': 'synthetic', 'source_url': 'https://fixture.example/wrong', 'name': 'Wrong batch'})
        wrong = export_batch(other, self.job.root / 'exports', include_files=True)
        target.write_bytes(wrong.read_bytes())
        value = run(self.job.root, self.job.id)
        self.assertEqual(value['state'], 'FAILED')
        self.assertEqual(value['last_seq'], 0)
        self.assertIn('не соответствует', value['error'])


if __name__ == '__main__':
    unittest.main()
