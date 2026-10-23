import hashlib
import json
import tempfile
import subprocess
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from espbs.archive import export_batch, verify_archive
from espbs.jobs import Job
from espbs.storage import Batch
from espbs.stream_parts import create_next
from espbs.retention import confirm_copy
from test_change_log import record


class StreamArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = Job.create(self.root)
        self.batch = Batch(self.root, self.parent.id)
        self.batch.enable_change_log()
        self.batch.add(record(1))
        self.batch.add(record(2))
        self.child = create_next(self.parent)
        self.target = Batch(self.root, self.child.id)

    def export(self, **kwargs):
        return export_batch(self.target, self.root / 'exports', **kwargs)

    def rewrite(self, path, edit):
        with zipfile.ZipFile(path) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        manifest = json.loads(members['manifest.json'])
        xml = ET.fromstring(members['products.xml'])
        edit(manifest, xml)
        members['products.xml'] = ET.tostring(xml)
        manifest['xml_bytes'] = len(members['products.xml'])
        manifest['xml_sha256'] = hashlib.sha256(members['products.xml']).hexdigest()
        members['manifest.json'] = json.dumps(manifest).encode()
        changed = self.root / 'changed.zip'
        with zipfile.ZipFile(changed, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)
        return changed

    def test_offline_range_and_immutable_versions(self):
        self.batch.add(record(1, 'Updated'))
        second = create_next(self.parent, 2)
        first_archive = self.export()
        second_archive = export_batch(Batch(self.root, second.id), self.root / 'exports')
        self.assertEqual(self.export(), first_archive)
        result = subprocess.run([sys.executable, '-S', '-m', 'espbs', 'verify', str(first_archive)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['stream_range'], {'after': 0, 'through': 2})
        # Move all databases out of reach: verification only reads the ZIP.
        (self.root / 'batches').rename(self.root / 'hidden-batches')
        (self.root / 'jobs').rename(self.root / 'hidden-jobs')
        for path, bounds in ((first_archive, {'after': 0, 'through': 2}),
                             (second_archive, {'after': 2, 'through': 3})):
            report = verify_archive(path)
            self.assertEqual(report['version'], 3)
            self.assertEqual(report['source_batch_id'], self.parent.id)
            self.assertEqual(report['stream_range'], bounds)
        with zipfile.ZipFile(first_archive) as archive:
            xml = ET.fromstring(archive.read('products.xml'))
            self.assertEqual({p.attrib['journal_seq'] for p in xml}, {'1', '2'})
            self.assertTrue(all(p.find("field[@name='name']").text == 'Original' for p in xml))

    def test_tampering_with_recomputed_xml_checksum(self):
        path = self.export()
        edits = [
            lambda m, x: m['stream_range'].update(after=True),
            lambda m, x: m['stream_range'].update(through=3),
            lambda m, x: m.update(source_batch_id=self.child.id),
            lambda m, x: x.set('source_batch_id', self.child.id),
            lambda m, x: x[0].set('journal_seq', x[1].get('journal_seq')),
            lambda m, x: x[0].set('journal_seq', '0'),
            lambda m, x: x[0].set('record_id', x[1].get('record_id')),
            lambda m, x: x.remove(x[0]),
            lambda m, x: m.update(version=1),
        ]
        for edit in edits:
            with self.subTest(edit=edit):
                with self.assertRaises(ValueError):
                    verify_archive(self.rewrite(path, edit))

    def test_embedded_mode_and_receipt_bind_range(self):
        path = self.export(include_files=True)
        report = verify_archive(path)
        self.assertEqual(report['attachments'], 'embedded-with-report')
        self.assertEqual(self.export(include_files=True), path)
        with self.assertRaisesRegex(ValueError, 'stream_range'):
            confirm_copy(self.child, {**report, 'stream_range': {'after': 1, 'through': 3}})
        saved = confirm_copy(self.child, report)['receipt']
        self.assertEqual(saved['stream_range'], report['stream_range'])
        self.assertEqual(saved['source_batch_id'], self.parent.id)

    def test_failed_publication_can_retry_same_snapshot(self):
        with patch('espbs.archive.os.link', side_effect=OSError('simulated full disk')):
            with self.assertRaises(OSError):
                self.export()
        self.assertEqual(self.target.info()['record_count'], 2)
        self.assertEqual(self.batch.info()['state'], 'OPEN')
        self.assertFalse((self.root / 'exports' / (self.child.id + '.zip')).exists())
        self.assertEqual(verify_archive(self.export())['stream_range'], {'after': 0, 'through': 2})

    def test_changed_snapshot_and_unpublished_child_rejected(self):
        with self.parent.db() as db:
            db.execute('UPDATE stream_parts SET ready=0')
        with self.assertRaisesRegex(ValueError, 'not published'):
            self.export()
        with self.parent.db() as db:
            db.execute('UPDATE stream_parts SET ready=1')
        with self.target.connection() as db:
            db.execute("UPDATE records SET payload='{}'")
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.export()

    def test_legacy_part_archive_is_preserved(self):
        with patch('espbs.archive.stream_snapshot', return_value=None):
            path = self.export()
        old_bytes = path.read_bytes()
        self.assertEqual(verify_archive(path)['version'], 1)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            self.export()
        self.assertEqual(path.read_bytes(), old_bytes)
        fresh = export_batch(self.target, self.root / 'new-exports')
        self.assertEqual(verify_archive(fresh)['version'], 3)
