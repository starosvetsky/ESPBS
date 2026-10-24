import tempfile
import unittest
from unittest.mock import patch

from espbs.jobs import Job
from espbs.storage import Batch, JournalLimitReached, canonical_json
from espbs.archive import export_batch, verify_archive
from espbs.retention import cleanup, confirm_copy
from test_jobs import PRODUCT, CATALOG
from test_change_log import record


class Client:
    def __init__(self, count):
        self.count, self.calls = count, []

    def get(self, url):
        self.calls.append(url)
        if url == CATALOG:
            return ''.join(f'<div class="good"><a href="/product/fixture-{i}/">Fixture</a></div>' for i in range(self.count))
        return PRODUCT


class StreamControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_window_stops_http_until_explicit_cleanup_then_resumes(self):
        job = Job.create(self.root, 60, streaming=True)
        client = Client(60)
        self.assertEqual(job.run(client)['state'], 'WAITING_PARTS')
        self.assertEqual(job.info()['completed'], 50)
        self.assertEqual(len(client.calls), 51)
        with job.db() as db:
            parts = list(db.execute('SELECT child_id,ready FROM stream_parts ORDER BY seq'))
        self.assertEqual(len(parts), 2)
        blocked = Client(60)
        self.assertEqual(job.run(blocked)['state'], 'WAITING_PARTS')
        self.assertEqual(blocked.calls, [])
        child = Job(self.root, parts[0]['child_id'])
        path = export_batch(Batch(self.root, child.id), job.root / 'exports')
        confirm_copy(child, verify_archive(path))
        self.assertEqual(job.run(blocked)['state'], 'WAITING_PARTS')
        self.assertEqual(blocked.calls, [])
        cleanup(child, child.id)
        remaining = Client(60)
        self.assertEqual(Job(self.root, job.id).run(remaining)['state'], 'COMPLETED')
        self.assertEqual(len(remaining.calls), 10)
        batch = Batch(self.root, job.id)
        self.assertEqual(len(batch.changes(limit=100)), 60)
        self.assertEqual(batch.info()['state'], 'OPEN')
        with job.db() as db:
            ranges = list(db.execute('SELECT start_seq,end_seq FROM stream_parts ORDER BY seq'))
        self.assertEqual([tuple(row) for row in ranges], [(0,25),(25,50),(50,60)])

    def test_pending_registration_is_recovered_before_new_requests(self):
        job = Job.create(self.root, 26, streaming=True)
        with patch('espbs.stream_registration.ensure_child', side_effect=RuntimeError('crash')):
            self.assertEqual(job.run(Client(26))['state'], 'FAILED')
        self.assertEqual(job.info()['completed'], 25)
        with job.db() as db:
            child_id = db.execute('SELECT child_id FROM stream_parts').fetchone()[0]
        resumed = Client(26)
        self.assertEqual(job.run(resumed)['state'], 'COMPLETED')
        self.assertEqual(len(resumed.calls), 1)
        self.assertEqual(Job(self.root, child_id).info()['completed'], 25)

    def test_journal_limit_and_replay_after_committed_record(self):
        with patch('espbs.stream_control.MAX_VERSIONS', 1):
            job = Job.create(self.root, 2, streaming=True)
        original = Batch.add
        def crash(batch, value):
            original(batch, value)
            raise RuntimeError('after commit')
        with patch.object(Batch, 'add', crash):
            self.assertEqual(job.run(Client(2))['state'], 'FAILED')
        self.assertEqual(job.info()['completed'], 0)
        self.assertEqual(job.run(Client(2))['state'], 'PAUSED_JOURNAL')
        self.assertEqual(job.info()['completed'], 1)
        batch = Batch(self.root, job.id)
        self.assertEqual(len(batch.changes()), 1)
        with batch.connection() as db:
            self.assertEqual(db.execute('SELECT versions FROM journal_budget').fetchone()[0], 1)

    def test_payload_limit_is_atomic_and_counts_utf8(self):
        batch = Batch.create(self.root)
        value = record(1, 'Русский текст')
        size = len(canonical_json(value).encode())
        batch.limit_change_log(10, size)
        batch.add(value)
        self.assertEqual(batch.add(value), 'unchanged')
        with self.assertRaises(JournalLimitReached):
            batch.add(record(2))
        self.assertEqual(batch.info()['record_count'], 1)
        self.assertEqual(len(batch.changes()), 1)
        with batch.connection() as db:
            self.assertEqual(db.execute('SELECT payload_bytes FROM journal_budget').fetchone()[0], size)

    def test_regular_job_is_not_changed(self):
        job = Job.create(self.root, 2)
        self.assertEqual(job.run(Client(2))['state'], 'COMPLETED')
        with Batch(self.root, job.id).connection() as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='record_changes'").fetchone())

    def test_failed_journal_write_rolls_back_budget(self):
        import sqlite3
        batch = Batch.create(self.root)
        batch.limit_change_log(1, 4096)
        with batch.connection() as db:
            db.execute("CREATE TRIGGER reject_version BEFORE INSERT ON record_changes BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            batch.add(record(1))
        with batch.connection() as db:
            self.assertEqual(tuple(db.execute('SELECT versions,payload_bytes FROM journal_budget').fetchone()), (0,0))
            db.execute('DROP TRIGGER reject_version')
        self.assertEqual(batch.add(record(1)), 'inserted')

    def test_concurrent_writers_cannot_exceed_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        batch = Batch.create(self.root)
        batch.limit_change_log(1, 4096)
        def add(n):
            try:
                return batch.add(record(n))
            except JournalLimitReached:
                return 'limited'
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(add, range(8)))
        self.assertEqual(results.count('inserted'), 1)
        self.assertEqual(results.count('limited'), 7)
        self.assertEqual(len(batch.changes()), 1)

    def test_stop_and_disk_pause_keep_stream_progress(self):
        job = Job.create(self.root, 2, streaming=True)
        self.assertEqual(job.run(Client(2), lambda e: job.stop() if e['kind']=='saved' else None)['state'], 'STOPPED')
        from espbs.disk import LowDiskSpace
        with patch('espbs.jobs.require_space', side_effect=LowDiskSpace('full')):
            self.assertEqual(job.run(Client(2))['state'], 'PAUSED_DISK')
        self.assertEqual(job.run(Client(2))['state'], 'COMPLETED')
        self.assertEqual(len(Batch(self.root, job.id).changes()), 2)

    def test_changed_source_cannot_block_committed_record_recovery(self):
        with patch('espbs.stream_control.MAX_VERSIONS', 1):
            job = Job.create(self.root, 1, streaming=True)
        with patch('espbs.catalog.Catalog.add', side_effect=RuntimeError('after batch commit')):
            self.assertEqual(job.run(Client(1))['state'], 'FAILED')
        self.assertEqual(job.info()['completed'], 0)
        class Changed(Client):
            def get(self, url):
                return super().get(url).replace('Synthetic MES', 'Changed MES')
        resumed = Changed(1)
        self.assertEqual(job.run(resumed)['state'], 'COMPLETED')
        self.assertEqual(resumed.calls, [])
        self.assertEqual(job.info()['completed'], 1)
        with job.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM item_commits').fetchone()[0], 0)
        from espbs.catalog import Catalog
        self.assertEqual(len(Catalog(self.root).products()), 1)

    def test_request_gate_blocks_parallel_snapshot_and_rechecks_window(self):
        from concurrent.futures import ThreadPoolExecutor
        from espbs.stream_parts import create_next
        from espbs.stream_control import request_slot, WaitingForParts
        job = Job.create(self.root, 3, streaming=True)
        batch = Batch(self.root, job.id)
        batch.limit_change_log(**job.info()['streaming'])
        batch.add(record(1))
        create_next(job)
        batch.add(record(2))
        with request_slot(job):
            with ThreadPoolExecutor(max_workers=1) as pool:
                other = pool.submit(create_next, job, 1)
                with self.assertRaisesRegex(ValueError, 'already running'):
                    other.result()
            with job.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM stream_parts').fetchone()[0], 1)
        create_next(job, 1)
        with self.assertRaises(WaitingForParts):
            with request_slot(job):
                self.fail('HTTP must not start with two occupied slots')
