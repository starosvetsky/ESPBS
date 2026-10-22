import tempfile
import unittest
from unittest.mock import patch

from espbs.job_index import connection, page, rebuild_missing
from espbs.jobs import Job


class JobIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_stable_pages_with_new_job_and_progress_changes(self):
        jobs = [Job.create(self.root) for _ in range(5)]
        first = page(self.root, limit=2)
        self.assertEqual([j['id'] for j in first['jobs']], [j.id for j in reversed(jobs[-2:])])
        Job.create(self.root)
        with jobs[0].db() as db:
            db.execute("UPDATE job SET updated_at='2999',state='STOPPED'")
        second = page(self.root, first['next_cursor'], 2)
        last = page(self.root, second['next_cursor'], 2)
        ids = [j['id'] for p in (first, second, last) for j in p['jobs']]
        self.assertEqual(ids, [j.id for j in reversed(jobs)])
        self.assertFalse(last['has_more'])
        self.assertIsNone(last['next_cursor'])

    def test_recovery_and_tied_timestamps(self):
        jobs = [Job.create(self.root) for _ in range(3)]
        for job in jobs:
            with job.db() as db:
                db.execute("UPDATE job SET created_at='2026-01-01'")
        with connection(self.root) as db:
            db.execute('DELETE FROM jobs')
        rebuild_missing(self.root)
        rebuild_missing(self.root)
        first = page(self.root, limit=1)
        rest = page(self.root, first['next_cursor'], 10)
        self.assertEqual([j['id'] for j in first['jobs'] + rest['jobs']],
                         sorted((j.id for j in jobs), reverse=True))

    def test_bounded_reads_and_invalid_parameters(self):
        for _ in range(4):
            Job.create(self.root)
        original = Job.reconcile
        with patch.object(Job, 'reconcile', autospec=True, side_effect=original) as read:
            with patch('espbs.api.archive_info', side_effect=AssertionError('Archive inspected')):
                self.assertEqual(len(page(self.root, limit=2)['jobs']), 2)
            self.assertEqual(read.call_count, 2)
        for limit in (0, 101, -1):
            with self.assertRaises(ValueError):
                page(self.root, limit=limit)
        for cursor in ('bad', '00000000-0000-0000-0000-000000000000'):
            with self.assertRaises(ValueError):
                page(self.root, cursor)
