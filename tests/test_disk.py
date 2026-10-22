import tempfile
import unittest
from unittest.mock import patch
from collections import namedtuple

from espbs.disk import MIB, LowDiskSpace, require_space, status
from espbs.jobs import Job
from espbs.storage import Batch
from espbs.archive import export_batch
from test_jobs import FakeClient, PRODUCT, URLS
from espbs.eltex import product

Usage = namedtuple('Usage', 'total used free')


class DiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_cached_totals_do_not_cache_headroom(self):
        with patch('espbs.disk._scan_sizes', return_value={'batches': 100}) as scan:
            with patch('espbs.disk.shutil.disk_usage', return_value=Usage(3000*MIB, 0, 2000*MIB)):
                first = status(self.root)
            with patch('espbs.disk.shutil.disk_usage', return_value=Usage(3000*MIB, 0, MIB)):
                second = status(self.root)
                with self.assertRaises(LowDiskSpace):
                    require_space(self.root)
            self.assertTrue(first['can_collect'])
            self.assertFalse(second['can_collect'])
            self.assertEqual(second['free_bytes'], MIB)
            self.assertEqual(scan.call_count, 1)
            first['sizes']['batches'] = 999
            self.assertEqual(status(self.root)['sizes']['batches'], 100)

    def test_summary_expires_and_separates_roots(self):
        with patch('espbs.disk.time.monotonic', return_value=100) as clock:
            with patch('espbs.disk._scan_sizes', return_value={'batches': 1}) as scan:
                status(self.root)
                clock.return_value = 129
                self.assertEqual(status(self.root)['sizes_age_seconds'], 29)
                self.assertEqual(scan.call_count, 1)
                clock.return_value = 130
                status(self.root)
                status(self.root + '/another')
                self.assertEqual(scan.call_count, 3)

    def test_concurrent_requests_share_one_scan(self):
        from concurrent.futures import ThreadPoolExecutor
        with patch('espbs.disk._scan_sizes', return_value={'batches': 1}) as scan:
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(status, [self.root] * 16))
            self.assertEqual(scan.call_count, 1)

    def test_disappearing_file_and_index_accounting(self):
        from pathlib import Path
        import sqlite3
        from contextlib import closing
        from espbs.disk import _file_size, _scan_sizes
        self.assertEqual(_file_size(Path(self.root) / 'missing'), 0)
        self.assertEqual(_file_size(Path(self.root)), 0)
        index = Path(self.root) / 'job-index.sqlite3'
        with closing(sqlite3.connect(index)) as db, db:
            db.execute('CREATE TABLE fixture (id INTEGER)')
        self.assertEqual(_scan_sizes(Path(self.root))['job-index'], index.stat().st_size)

    def test_scan_failure_is_not_cached(self):
        with patch('espbs.disk._scan_sizes', side_effect=[PermissionError('denied'), {'jobs': 2}]) as scan:
            with self.assertRaises(PermissionError):
                status(self.root)
            self.assertEqual(status(self.root)['sizes'], {'jobs': 2})
            self.assertEqual(scan.call_count, 2)

    def test_refuses_new_job_without_creating_data(self):
        with patch('espbs.disk.shutil.disk_usage', return_value=Usage(2000*MIB, 1999*MIB, MIB)):
            with self.assertRaises(LowDiskSpace):
                Job.create(self.root)
            self.assertFalse(status(self.root)['can_collect'])
        from pathlib import Path
        self.assertEqual(list(Path(self.root).iterdir()), [])

    def test_pause_preserves_progress_and_resume(self):
        job = Job.create(self.root, 2)
        def check(*args):
            if job.info()['completed'] == 1:
                raise LowDiskSpace('disk reserve')
        with patch('espbs.jobs.require_space', side_effect=check):
            result = job.run(FakeClient())
        self.assertEqual(result['state'], 'PAUSED_DISK')
        self.assertEqual(result['completed'], 1)
        self.assertEqual(Batch(self.root, job.id).info()['record_count'], 1)
        self.assertEqual(job.run(FakeClient())['completed'], 2)

    def test_export_refusal_leaves_batch_open(self):
        batch = Batch.create(self.root)
        batch.add(product(PRODUCT, URLS[0]))
        with patch('espbs.disk.shutil.disk_usage', return_value=Usage(1, 1, 0)):
            with self.assertRaises(LowDiskSpace):
                export_batch(batch, self.root + '/exports')
        self.assertEqual(batch.info()['state'], 'OPEN')
        self.assertEqual(batch.info()['record_count'], 1)

    def test_invalid_reserve(self):
        with patch.dict('os.environ', {'ESPBS_DISK_RESERVE_MIB': '0'}):
            with self.assertRaises(ValueError):
                require_space(self.root)
