import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from espbs.jobs import Job
from espbs.storage import Batch
from espbs.stream_parts import create_next
from espbs.job_index import rebuild_missing
from test_change_log import record


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = Job.create(self.root)
        self.batch = Batch(self.root, self.parent.id)
        self.batch.enable_change_log()
        self.batch.add(record(1))

    def saved(self):
        with self.parent.db() as db:
            return dict(db.execute('SELECT * FROM stream_parts').fetchone())

    def recover(self, expected):
        self.batch.add(record(2))
        child = create_next(Job(self.root, self.parent.id))
        self.assertEqual(child.id, expected)
        self.assertEqual(child.info()['stream_range'], {'after': 0, 'through': 1})
        self.assertEqual(child.info()['completed'], 1)
        self.assertEqual(len(list((self.root / 'jobs').glob('*.sqlite3'))), 2)
        self.assertEqual(len(list((self.root / 'batches').glob('*.sqlite3'))), 2)
        self.assertEqual(create_next(self.parent).id, expected)
        return child

    def test_intent_committed_before_any_child_files(self):
        with patch('espbs.stream_registration.ensure_child', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                create_next(self.parent)
        saved = self.saved()
        self.assertFalse((self.root / 'jobs' / (saved['child_id'] + '.sqlite3')).exists())
        self.assertFalse((self.root / 'batches' / (saved['child_id'] + '.sqlite3')).exists())
        self.recover(saved['child_id'])

    def test_batch_exists_but_job_not_created(self):
        with patch('espbs.stream_registration._job', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                create_next(self.parent)
        saved = self.saved()
        self.assertTrue((self.root / 'batches' / (saved['child_id'] + '.sqlite3')).exists())
        self.recover(saved['child_id'])

    def test_index_failure_after_job_created(self):
        with patch('espbs.job_index.register', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                create_next(self.parent)
        saved = self.saved()
        rebuild_missing(self.root)
        self.recover(saved['child_id'])

    def test_process_exit_mid_schema_and_index_restart(self):
        self.crash_schema('job')

    def test_process_exit_mid_batch_schema(self):
        self.crash_schema('batch')

    def crash_schema(self, kind):
        code = '''
import os, sys, sqlite3
from unittest.mock import patch
from espbs.jobs import Job
from espbs.stream_parts import create_next
from espbs import stream_registration as registration
kind = sys.argv[3]
original = getattr(registration, '_' + kind)
connect = sqlite3.connect
class CrashConnection(sqlite3.Connection):
    def execute(self, statement, *args):
        value = super().execute(statement, *args)
        if statement.startswith('CREATE TABLE ' + ('items' if kind == 'job' else 'records')):
            os._exit(17)
        return value
def crash_job(*args):
    with patch('sqlite3.connect', side_effect=lambda *a, **k: connect(*a, **k, factory=CrashConnection)):
        return original(*args)
setattr(registration, '_' + kind, crash_job)
create_next(Job(sys.argv[1],sys.argv[2]))
'''
        process = subprocess.run([sys.executable, '-c', code, str(self.root), self.parent.id, kind],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 17, process.stderr.decode(errors='replace'))
        saved = self.saved()
        directory = self.root / ('jobs' if kind == 'job' else 'batches')
        self.assertFalse((directory / (saved['child_id'] + '.sqlite3')).exists())
        self.assertTrue((directory / (saved['child_id'] + '.pending')).exists())
        rebuild_missing(self.root)
        self.recover(saved['child_id'])
        self.assertFalse(list(directory.glob('*.pending')))

    def test_mismatching_child_is_not_overwritten(self):
        with patch('espbs.stream_parts._copy', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                create_next(self.parent)
        child = Job(self.root, self.saved()['child_id'])
        with child.db() as db:
            config = json.loads(db.execute('SELECT value FROM config').fetchone()[0])
            config['parent_id'] = 'different'
            db.execute('UPDATE config SET value=?', (json.dumps(config),))
        with self.assertRaisesRegex(ValueError, 'configuration mismatch'):
            create_next(self.parent)
        self.assertEqual(child.info()['parent_id'], 'different')
