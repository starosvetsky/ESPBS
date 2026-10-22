import json
import tempfile
import unittest
from unittest.mock import patch

from espbs.jobs import Job, worker_lock
from espbs.storage import Batch
from espbs.stream_parts import create_next
from espbs.archive import export_batch, verify_archive
from espbs.retention import confirm_copy, cleanup
from test_change_log import record


class StreamPartsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Job.create(self.temp.name)
        self.batch = Batch(self.temp.name, self.job.id)
        self.batch.enable_change_log()

    def test_live_collector_and_duplicate_versions(self):
        self.batch.add(record(1))
        self.batch.add(record(2))
        self.batch.add(record(1, 'New version'))
        with worker_lock(self.job.path.with_suffix('.lock')):
            with self.job.db() as db:
                db.execute("UPDATE job SET state='RUNNING'")
            first = create_next(self.job)
            self.batch.add(record(3))
            second = create_next(self.job, first.info()['stream_range']['through'])
        old = list(Batch(self.temp.name, first.id).records())
        self.assertEqual(len(old), 2)
        self.assertTrue(all(json.loads(row['payload'])['name'] == 'Original' for row in old))
        self.assertEqual(second.info()['stream_range'], {'after': 2, 'through': 4})
        self.assertEqual(self.batch.info()['state'], 'OPEN')
        self.assertEqual(create_next(self.job).id, first.id)
        self.assertIsNone(create_next(self.job, 4))

    def test_interrupted_copy_reuses_fixed_range(self):
        self.batch.add(record(1))
        self.batch.add(record(2))
        from espbs.stream_parts import _copy
        def interrupted(target, rows):
            _copy(target, rows[:1])
            raise RuntimeError('interrupted after a committed partial copy')
        with patch('espbs.stream_parts._copy', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                create_next(self.job)
        with self.job.db() as db:
            saved = dict(db.execute('SELECT * FROM stream_parts').fetchone())
        self.batch.add(record(3))
        self.batch.add(record(1, 'Updated'))
        child = create_next(self.job)
        self.assertEqual(child.id, saved['child_id'])
        rows = list(Batch(self.temp.name, child.id).records())
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(json.loads(row['payload'])['name'] == 'Original' for row in rows))
        self.assertEqual(child.info()['stream_range']['through'], 2)

    def test_window_and_explicit_verified_cleanup(self):
        for n in range(51):
            self.batch.add(record(n))
        first = create_next(self.job)
        second = create_next(self.job, 25)
        self.assertEqual(second.info()['completed'], 25)
        with self.assertRaisesRegex(ValueError, 'explicitly clean'):
            create_next(self.job, 50)
        archive = export_batch(Batch(self.temp.name, first.id), self.job.root / 'exports')
        report = verify_archive(archive)
        confirm_copy(first, report)
        with self.assertRaisesRegex(ValueError, 'explicitly clean'):
            create_next(self.job, 50)
        cleanup(first, first.id)
        third = create_next(self.job, 50)
        self.assertEqual(third.info()['completed'], 1)
        self.assertEqual(len(self.batch.changes(limit=100)), 51)

    def test_invalid_cursor_and_no_journal(self):
        for value in (-1, True, '0', 2**63):
            with self.assertRaises(ValueError):
                create_next(self.job, value)
        with self.assertRaises(ValueError):
            create_next(self.job, 3)
        with self.assertRaisesRegex(ValueError, 'not enabled'):
            create_next(Job.create(self.temp.name))

    def test_tampered_pending_snapshot_is_rejected(self):
        self.batch.add(record(1))
        with patch('espbs.stream_parts._copy', side_effect=RuntimeError()):
            with self.assertRaises(RuntimeError):
                create_next(self.job)
        with self.batch.connection() as db:
            db.execute("UPDATE record_changes SET payload='{}'")
        with self.assertRaisesRegex(ValueError, 'no longer matches'):
            create_next(self.job)

    def test_unpublished_part_cannot_be_cleaned_and_recovers(self):
        self.batch.add(record(1))
        child = create_next(self.job)
        with self.job.db() as db:
            db.execute('UPDATE stream_parts SET ready=0')
        with self.assertRaisesRegex(ValueError, 'публикацию'):
            cleanup(child, child.id)
        self.assertEqual(create_next(self.job).id, child.id)

    def test_low_disk_does_not_register_a_part(self):
        from espbs.disk import LowDiskSpace
        self.batch.add(record(1))
        with patch('espbs.stream_parts.require_space', side_effect=LowDiskSpace('full')):
            with self.assertRaises(LowDiskSpace):
                create_next(self.job)
        with self.job.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM stream_parts').fetchone()[0], 0)
        self.assertEqual(self.batch.info()['state'], 'OPEN')
