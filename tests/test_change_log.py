import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from espbs.storage import Batch


def record(number, name='Original'):
    return {'source': 'fixture', 'source_url': f'https://example.invalid/{number}',
            'external_id': str(number), 'name': name}


class ChangeLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.batch = Batch.create(self.temp.name)
        self.batch.enable_change_log()

    def test_versions_and_unchanged_replay(self):
        self.assertEqual(self.batch.add(record(1)), 'inserted')
        original = self.batch.changes()[0]
        self.assertEqual(self.batch.add(record(1)), 'unchanged')
        self.assertEqual(len(self.batch.changes()), 1)
        self.assertEqual(self.batch.add(record(1, 'Updated')), 'updated')
        rows = self.batch.changes()
        self.assertEqual(rows[0], original)
        self.assertEqual(rows[1]['seq'], 2)
        self.assertEqual(rows[0]['record_id'], rows[1]['record_id'])
        for row in rows:
            self.assertEqual(hashlib.sha256(row['payload'].encode()).hexdigest(), row['content_sha256'])
        self.batch.add(record(1))  # A real reversal is a new version, not a duplicate.
        self.assertEqual(len(self.batch.changes()), 3)

    def test_cursor_does_not_skip_later_lower_hash(self):
        for n in range(20):
            self.batch.add(record(n))
        rows = self.batch.changes()
        self.assertNotEqual([r['record_id'] for r in rows], sorted(r['record_id'] for r in rows))
        cursor = 0
        seen = []
        while page := self.batch.changes(cursor, 3):
            seen.extend(page)
            cursor = page[-1]['seq']
        self.assertEqual(seen, rows)
        self.batch.add(record(21))
        self.assertEqual(self.batch.changes(cursor)[0]['seq'], 21)

    def test_journal_failure_rolls_back_live_record(self):
        self.batch.add(record(1))
        before = list(self.batch.records())
        with self.batch.connection() as db:
            db.execute("CREATE TRIGGER reject_change BEFORE INSERT ON record_changes "
                       "BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.batch.add(record(1, 'Not committed'))
        self.assertEqual(list(self.batch.records()), before)
        self.assertEqual(len(self.batch.changes()), 1)
        with self.batch.connection() as db:
            db.execute('DROP TRIGGER reject_change')
        self.batch.add(record(1, 'Not committed'))
        self.assertEqual(len(self.batch.changes()), 2)

    def test_concurrent_replay_commits_one_version(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.batch.add, [record(1)] * 8))
        self.assertEqual(results.count('inserted'), 1)
        self.assertEqual(results.count('unchanged'), 7)
        self.assertEqual(len(self.batch.changes()), 1)

    def test_old_batches_are_not_silently_migrated(self):
        old = Batch.create(self.temp.name)
        old.add(record(1))
        with self.assertRaises(ValueError):
            old.enable_change_log()
        with self.assertRaises(ValueError):
            old.changes()
        self.assertEqual(old.add(record(2)), 'inserted')

    def test_restart_idempotence_and_validation(self):
        self.batch.add(record(1))
        recovered = Batch(self.temp.name, self.batch.id)
        recovered.enable_change_log()
        self.assertEqual(recovered.add(record(1)), 'unchanged')
        self.assertEqual(len(recovered.changes()), 1)
        for cursor in (-1, True, '1', 2**63):
            with self.assertRaises(ValueError):
                recovered.changes(cursor)
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                recovered.changes(limit=limit)

    def test_cleanup_cannot_discard_unexported_versions(self):
        from espbs.jobs import Job
        from espbs.retention import cleanup
        job = Job.create(self.temp.name)
        batch = Batch(self.temp.name, job.id)
        batch.enable_change_log()
        batch.add(record(1))
        with self.assertRaisesRegex(ValueError, 'журнал версий'):
            cleanup(job, job.id)
        self.assertEqual(len(batch.changes()), 1)
        self.assertEqual(batch.info()['record_count'], 1)
