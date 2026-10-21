import tempfile
import unittest
from unittest.mock import patch

from espbs.jobs import Job
from espbs.storage import Batch
from espbs.partitions import create_next, summary
from espbs.archive import export_batch, verify_archive
from espbs.retention import cleanup, confirm_copy
from espbs.disk import LowDiskSpace


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Job.create(self.temp.name, 60)
        self.batch = Batch(self.temp.name, self.job.id)
        for i in range(60):
            self.batch.add({'source': 'synthetic', 'source_url': f'https://fixture.example/{i}',
                            'name': f'Synthetic {i}', 'documents': [
                                {'url': f'https://fixture.example/{i}-{n}.pdf'} for n in range(3)]})
        with self.job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")

    def test_all_records_exactly_once_and_repeat_is_idempotent(self):
        original = list(self.batch.records())
        copied = []
        after = ''
        while True:
            child = create_next(self.job, after)
            self.assertEqual(create_next(self.job, after).id, child.id)
            self.assertEqual(child.info()['state'], 'COMPLETED')
            records = list(Batch(self.temp.name, child.id).records())
            self.assertLessEqual(len(records), 13)
            copied.extend(records)
            state = summary(self.job)
            if state['done']:
                break
            after = state['next_cursor']
        self.assertEqual(copied, original)
        self.assertEqual(original, list(self.batch.records()))
        self.assertEqual(summary(self.job)['count'], 5)
        with self.assertRaises(ValueError):
            create_next(self.job, summary(self.job)['next_cursor'])

    def test_interrupted_copy_can_resume_and_blocks_parent_cleanup(self):
        real = __import__('espbs.partitions', fromlist=['require_space']).require_space
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise LowDiskSpace('synthetic interrupted copy')
            return real(*args, **kwargs)
        with patch('espbs.partitions.require_space', side_effect=fail_second):
            with self.assertRaises(LowDiskSpace):
                create_next(self.job)
        pending = summary(self.job)['recent'][0]
        self.assertFalse(pending['ready'])
        path = export_batch(self.batch, self.job.root / 'exports')
        confirm_copy(self.job, verify_archive(path))
        with self.assertRaisesRegex(ValueError, 'копирования'):
            cleanup(self.job, self.job.id)
        child = create_next(self.job)
        self.assertEqual(child.id, pending['child_id'])
        self.assertEqual(child.info()['completed'], 13)
        self.assertEqual(self.batch.info()['record_count'], 60)

    def test_invalid_cursor_running_parent_and_recursive_partition_rejected(self):
        with self.assertRaises(ValueError):
            create_next(self.job, 'arbitrary')
        child = create_next(self.job)
        with self.assertRaises(ValueError):
            create_next(child)
        with self.job.db() as db:
            db.execute("UPDATE job SET state='RUNNING'")
        with self.assertRaises(ValueError):
            create_next(self.job, summary(self.job)['next_cursor'])

    def test_child_archive_and_parent_cleanup_are_independent(self):
        child = create_next(self.job)
        target = Batch(self.temp.name, child.id)
        child_path = export_batch(target, self.job.root / 'exports')
        before = child_path.read_bytes()
        parent_path = export_batch(self.batch, self.job.root / 'exports')
        confirm_copy(self.job, verify_archive(parent_path))
        cleanup(self.job, self.job.id)
        self.assertEqual(target.info()['record_count'], 13)
        self.assertEqual(before, child_path.read_bytes())
        self.assertEqual(verify_archive(child_path)['record_count'], 13)
        with self.assertRaises(ValueError):
            create_next(self.job, summary(self.job)['next_cursor'])

    def test_one_large_record_does_not_stall_and_is_not_modified(self):
        job = Job.create(self.temp.name, 1)
        batch = Batch(self.temp.name, job.id)
        batch.add({'source': 'synthetic', 'source_url': 'https://fixture.example/large', 'name': 'Synthetic large',
                   'documents': [{'url': f'https://fixture.example/{i}.pdf'} for i in range(70)]})
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        child = create_next(job)
        self.assertEqual(list(batch.records()), list(Batch(self.temp.name, child.id).records()))
        self.assertTrue(summary(job)['done'])
        self.assertEqual(summary(job)['recent'][0]['reference_count'], 70)


if __name__ == '__main__':
    unittest.main()
