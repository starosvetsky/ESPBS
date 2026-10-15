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
