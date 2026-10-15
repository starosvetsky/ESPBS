import tempfile
import unittest
from unittest.mock import patch

from espbs.jobs import Job
from espbs.storage import Batch
from espbs.archive import export_batch, verify_archive
from espbs.retention import confirm_copy, cleanup, receipt
from test_jobs import FakeClient


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Job.create(self.temp.name, 1)
        self.job.run(FakeClient())
        self.batch = Batch(self.temp.name, self.job.id)
        self.path = export_batch(self.batch, self.job.root / 'exports')
        self.report = verify_archive(self.path)

    def test_requires_matching_report_and_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            cleanup(self.job, self.job.id)
        bad = dict(self.report, archive_sha256='wrong')
        with self.assertRaises(ValueError):
            confirm_copy(self.job, bad)
        confirm_copy(self.job, self.report)
        self.assertEqual(self.batch.info()['record_count'], 1)
        with self.assertRaises(ValueError):
            cleanup(self.job, 'yes')
        self.assertTrue(self.path.exists())

    def test_cleanup_keeps_history_and_is_repeatable(self):
        confirm_copy(self.job, self.report)
        self.assertEqual(cleanup(self.job, self.job.id)['state'], 'CLEANED')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.batch.info()['record_count'], 0)
        self.assertEqual(receipt(self.job)['receipt']['record_count'], 1)
        self.assertEqual(cleanup(self.job, self.job.id)['state'], 'CLEANED')
        with self.assertRaises(ValueError):
            export_batch(self.batch, self.job.root / 'exports')

    def test_interrupted_cleanup_retries(self):
        confirm_copy(self.job, self.report)
        with patch('pathlib.Path.unlink', side_effect=OSError('busy')):
            with self.assertRaises(OSError):
                cleanup(self.job, self.job.id)
        self.assertEqual(receipt(self.job)['state'], 'CLEANING')
        self.assertTrue(self.path.exists())
        self.assertEqual(cleanup(self.job, self.job.id)['state'], 'CLEANED')

    def test_changed_archive_blocks_cleanup(self):
        confirm_copy(self.job, self.report)
        self.path.write_bytes(b'broken')
        with self.assertRaises(Exception):
            cleanup(self.job, self.job.id)
        self.assertEqual(self.batch.info()['record_count'], 1)
