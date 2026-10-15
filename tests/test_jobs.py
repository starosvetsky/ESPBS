"""Synthetic HTML fixtures; no network calls in unit tests."""
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from espbs.eltex import CATALOG, Client, listing, product, safe_url
from espbs.jobs import Job, worker_lock
from espbs.storage import Batch
from espbs.archive import export_batch, verify_archive


URLS = ['https://eltex.ru/product/a/', 'https://eltex.ru/product/b/']
LISTING = ''.join('<div class="good"><a href="%s">item</a></div>' % url.replace('https://eltex.ru', '') for url in URLS)
PRODUCT = '<h1>Synthetic MES</h1><script type="application/ld+json">' + json.dumps({
    '@type': 'Product', 'name': 'Synthetic MES', 'brand': {'name': 'Eltex'},
    'additionalProperty': [{'name': 'Ports', 'value': '24'}]}) + '</script>'


class FakeClient:
    def __init__(self):
        self.calls = []
    def get(self, url):
        self.calls.append(url)
        return LISTING if url == CATALOG else PRODUCT


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_parse_and_scope(self):
        urls, _ = listing(LISTING + '<a href="/product/promo/">promo</a>', CATALOG)
        self.assertEqual(urls, URLS)
        result = product(PRODUCT, URLS[0])
        self.assertEqual(result['attributes']['Ports'], ['24'])
        self.assertEqual(result['quality']['status'], 'REVIEW')
        self.assertEqual(result['mpn'], '')
        for url in ('http://eltex.ru/', 'https://other.invalid/', 'https://eltex.ru@evil.invalid/'):
            with self.assertRaises(ValueError):
                safe_url(url)
        with self.assertRaises(ValueError):
            product('<h1>Blocked</h1>', URLS[0])
        with self.assertRaises(ValueError):
            listing('<h1>Blocked</h1>', CATALOG)

    def test_stop_resume_export(self):
        job = Job.create(self.root, 2)
        client = FakeClient()
        result = job.run(client, lambda e: job.stop() if e['kind'] == 'saved' else None)
        self.assertEqual(result['state'], 'STOPPED')
        self.assertEqual(result['completed'], 1)
        next_client = FakeClient()
        result = Job(self.root, job.id).run(next_client)
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(next_client.calls, [URLS[1]])
        batch = Batch(self.root, job.id)
        self.assertEqual(batch.info()['record_count'], 2)
        archive = export_batch(batch, self.root + '/exports')
        self.assertEqual(verify_archive(archive)['record_count'], 2)

    def test_failure_and_replay_after_commit(self):
        job = Job.create(self.root, 1)
        original = Batch.add
        def committed_then_crashed(batch, record):
            original(batch, record)
            raise RuntimeError('crash after commit')
        with patch.object(Batch, 'add', committed_then_crashed):
            self.assertEqual(job.run(FakeClient())['state'], 'FAILED')
        self.assertEqual(job.info()['completed'], 0)
        self.assertEqual(Batch(self.root, job.id).info()['record_count'], 1)
        self.assertEqual(job.run(FakeClient())['completed'], 1)
        self.assertEqual(Batch(self.root, job.id).info()['record_count'], 1)

    def test_single_worker_and_export_guard(self):
        job = Job.create(self.root, 1)
        batch = Batch(self.root, job.id)
        batch.add(product(PRODUCT, URLS[0]))
        with worker_lock(job.path.with_suffix('.lock')):
            with self.assertRaises(ValueError):
                job.run(FakeClient())
            with self.assertRaises(ValueError):
                batch.seal()

    def test_limits(self):
        for limit in (0, -1, 1_000_001):
            with self.assertRaises(ValueError):
                Job.create(self.root, limit)
        self.assertEqual(Job.create(self.root, 1_000_000).info()['target'], 1_000_000)

    def test_http_error_preserves_checkpoint(self):
        job = Job.create(self.root, 1)
        with patch.object(FakeClient, 'get', side_effect=RuntimeError('HTTP 429')):
            result = job.run(FakeClient())
        self.assertEqual(result['state'], 'FAILED')
        self.assertEqual(result['completed'], 0)
        self.assertEqual(job.run(FakeClient())['state'], 'COMPLETED')

    def test_http_limits_robots_and_redirects(self):
        client = Client()
        self.addCleanup(client.close)
        response = MagicMock()
        response.headers = {'Location': 'https://other.invalid/'}
        response.__enter__.return_value = response
        response.is_redirect = False
        response.iter_content.return_value = [b'User-agent: *\nDisallow: /product/*\n']
        with patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'robots'):
                client.get(URLS[0])
            self.assertEqual(get.call_count, 1)
        client = Client()
        self.addCleanup(client.close)
        response.is_redirect = True
        with patch.object(client.session, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, 'redirected'):
                client.get('https://eltex.ru/robots.txt')
        response.is_redirect = False
        response.iter_content.return_value = [b'x' * (6 * 1024 * 1024 + 1)]
        client.last_request = 0
        with patch.object(client.session, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, '6 MiB'):
                client.get('https://eltex.ru/robots.txt')


if __name__ == '__main__':
    unittest.main()
