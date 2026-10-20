"""Synthetic fixtures only; no requests to external websites."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from espbs.archive import export_batch, verify_archive
from espbs.storage import Batch
from espbs.universal import Client
from espbs.robots import Robots
from espbs.disk import LowDiskSpace

PDF = b'%PDF-1.4\nsynthetic-test-not-a-real-document\n%%EOF'


class FakeClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def get(self, url, sink, max_bytes):
        self.calls.append(url)
        self.last_url = url
        if 'denied' in url:
            raise ValueError('robots.txt запрещает')
        data = b'<html>captcha</html>' if 'html' in url else PDF
        sink(data)
        return {'bytes': len(data), 'content_type': 'application/pdf'}

    def close(self):
        pass


class AttachmentsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.batch = Batch.create(self.root)
        self.output = self.root / 'exports'
        self.patch = patch('espbs.attachments.Client', FakeClient)
        self.patch.start()
        FakeClient.calls = []

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def add(self, number=1, docs=None, **kwargs):
        self.batch.add({'source': 'synthetic', 'source_url': f'https://fixture.example/p/{number}',
                        'name': 'Synthetic product', 'documents': docs or [
                            {'url': 'https://fixture.example/a.pdf'},
                            {'url': 'https://fixture.example/b.pdf'}], **kwargs})

    def build(self):
        path = export_batch(self.batch, self.output, include_files=True)
        report = verify_archive(path)
        with zipfile.ZipFile(path) as archive:
            entries = [json.loads(x) for x in archive.read('attachments.jsonl').splitlines()]
        return path, report, entries

    def test_roundtrip_dedup_repeat_keeps_original_records(self):
        self.add()
        self.add(2)
        original = [dict(r) for r in self.batch.records()]
        path, report, entries = self.build()
        self.assertEqual(report['version'], 2)
        self.assertEqual(report['attachment_summary']['unique_files'], 1)
        self.assertEqual(report['attachment_summary']['embedded'], 4)
        self.assertEqual(len(FakeClient.calls), 2)
        self.assertEqual(len({e['path'] for e in entries}), 1)
        self.assertEqual(original, [dict(r) for r in self.batch.records()])
        self.assertEqual(export_batch(self.batch, self.output, True), path)
        self.assertEqual(len(FakeClient.calls), 2)

    def test_failed_and_skipped_have_no_fake_local_path(self):
        self.add(docs=[{'url': 'https://fixture.example/denied.pdf'},
                       {'url': 'https://fixture.example/html.pdf'},
                       {'url': 'https://cdn.example/a.pdf'},
                       {'url': 'https://fixture.example/a.zip'}])
        _, report, entries = self.build()
        self.assertEqual(report['attachment_summary']['failed'], 2)
        self.assertEqual(report['attachment_summary']['skipped'], 2)
        self.assertTrue(all('path' not in e for e in entries))

    def test_limit_is_explicit_and_no_more_network_calls(self):
        self.add()
        with patch('espbs.attachments.MAX_ATTEMPTS', 1):
            _, report, entries = self.build()
        self.assertEqual(report['attachment_summary']['embedded'], 1)
        self.assertEqual(entries[1]['status'], 'skipped')
        self.assertEqual(len(FakeClient.calls), 1)

    def test_olnisa_images_never_download(self):
        self.batch.add({'source': 'synthetic', 'source_url': 'https://olnisa.ru/product/a',
                        'name': 'Synthetic', 'images': ['https://olnisa.ru/a.jpg']})
        _, report, _ = self.build()
        self.assertEqual(report['attachment_summary']['skipped'], 1)
        self.assertFalse(FakeClient.calls)

    def test_existing_v1_never_overwritten(self):
        self.add()
        path = export_batch(self.batch, self.output)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'не перезаписывается'):
            export_batch(self.batch, self.output, True)
        self.assertEqual(before, path.read_bytes())

    def rewrite(self, path, transform):
        with zipfile.ZipFile(path) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        transform(members)
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def test_corruption_rejected(self):
        self.add()
        path, _, entries = self.build()
        self.rewrite(path, lambda members: members.update({entries[0]['path']: b'X' * len(PDF)}))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_archive(path)

    def test_unlisted_member_rejected(self):
        self.add()
        path, _, _ = self.build()
        self.rewrite(path, lambda members: members.update({'../escape': b'bad'}))
        with self.assertRaisesRegex(ValueError, 'members'):
            verify_archive(path)

    def test_index_corruption_rejected(self):
        self.add()
        path, _, _ = self.build()
        self.rewrite(path, lambda members: members.update(
            {'attachments.jsonl': members['attachments.jsonl'].replace(b'fixture', b'changed')}))
        with self.assertRaisesRegex(ValueError, 'index'):
            verify_archive(path)

    def test_low_disk_aborts_without_publishing_or_losing_records(self):
        self.add()
        with patch('espbs.attachments.require_space', side_effect=LowDiskSpace('test')):
            with self.assertRaises(LowDiskSpace):
                self.build()
        self.assertFalse((self.output / (self.batch.id + '.zip')).exists())
        self.assertEqual(self.batch.info()['record_count'], 1)
        self.build()

    def test_network_timeout_is_reported_without_losing_cards(self):
        self.add()
        with patch.object(FakeClient, 'get', side_effect=TimeoutError('fixture timeout')):
            _, report, entries = self.build()
        self.assertEqual(report['attachment_summary']['failed'], 2)
        self.assertTrue(all('Сетевая ошибка' in e['reason'] for e in entries))
        self.assertEqual(self.batch.info()['record_count'], 1)

    def test_binary_client_robots_and_cross_host_redirect(self):
        client = Client('https://fixture.example/p', root=self.root)
        with patch.object(client, '_request', return_value='User-agent: *\nDisallow: /secret'):
            with self.assertRaisesRegex(ValueError, 'robots'):
                client.get('https://fixture.example/secret.pdf', sink=lambda c: None)
        with self.assertRaisesRegex(ValueError, 'пределы'):
            client.get('https://other.example/a.pdf', sink=lambda c: None)

    def test_binary_client_size_and_truncation(self):
        client = Client('https://fixture.example/', root=self.root)
        client.rules = Robots()
        client.rules.parse([])
        client.delay = 0
        response = MagicMock()
        response.status = 200
        response.getheader.side_effect = lambda key, default=None: '100' if key == 'Content-Length' else default
        response.read.side_effect = [b'short', b'']
        conn = MagicMock()
        conn.getresponse.return_value = response
        with patch('espbs.universal.public_addresses', return_value=['8.8.8.8']), \
                patch('espbs.universal.http.client.HTTPSConnection', return_value=conn):
            with self.assertRaisesRegex(ValueError, 'лимит'):
                client._request_locked('https://fixture.example/a.pdf', sink=lambda c: None, max_bytes=50)
            with self.assertRaisesRegex(ValueError, 'оборван'):
                client._request_locked('https://fixture.example/a.pdf', sink=lambda c: None, max_bytes=150)
        self.assertTrue(conn.close.called)

    def test_background_queue_is_idempotent_and_recovers_stale_task(self):
        from espbs.export_tasks import start, status, save
        from espbs.jobs import worker_lock
        with patch('espbs.export_tasks.subprocess.Popen') as popen:
            self.assertEqual(start(self.root, self.batch.id)['state'], 'QUEUED')
            self.assertEqual(start(self.root, self.batch.id)['state'], 'QUEUED')
            self.assertEqual(popen.call_count, 1)
        save(self.batch, 'RUNNING')
        with self.batch.connection() as db:
            db.execute('UPDATE export_task SET updated=0')
        with worker_lock(self.batch.path.with_suffix('.export-worker.lock')):
            self.assertEqual(status(self.batch)['state'], 'RUNNING')
        self.assertEqual(status(self.batch)['state'], 'FAILED')

    def test_background_run_and_verified_cleanup_include_files(self):
        from espbs.export_tasks import run, status
        from espbs.jobs import Job
        from espbs.retention import confirm_copy, cleanup
        job = Job.create(self.root, 1)
        batch = Batch(self.root, job.id)
        batch.add({'source': 'synthetic', 'source_url': 'https://fixture.example/p',
                   'name': 'Synthetic', 'documents': [{'url': 'https://fixture.example/a.pdf'}]})
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        path = Path(run(self.root, job.id)['archive'])
        self.assertEqual(status(batch)['state'], 'COMPLETED')
        report = verify_archive(path)
        self.assertEqual(report['attachment_summary']['unique_files'], 1)
        confirm_copy(job, report)
        self.assertTrue(path.exists())
        self.assertEqual(cleanup(job, job.id)['state'], 'CLEANED')
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
