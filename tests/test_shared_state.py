"""Synthetic shared-state and restart tests; no external requests."""
import multiprocessing
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
from espbs.catalog import Catalog
from espbs.traffic import Traffic, SourceBlocked
from espbs.eltex import Stopped


def request_process(root, queue):
    with Traffic(root).request('https://example.org/item', 2, lambda: False):
        queue.put(time.time())


class SharedStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def test_processes_share_domain_budget(self):
        Traffic(self.root)
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        processes = [context.Process(target=request_process, args=(self.root, queue)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            times = sorted(queue.get(timeout=15) for _ in processes)
            self.assertGreaterEqual(times[1] - times[0], 1.95)
            for process in processes:
                process.join(10)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join()
            queue.close()
            queue.join_thread()

    def test_blocks_survive_new_clients_and_are_host_scoped(self):
        traffic = Traffic(self.root)
        with self.assertRaises(SourceBlocked):
            traffic.response('https://example.org/a', 403)
        with self.assertRaises(SourceBlocked):
            with Traffic(self.root).request('https://example.org/b', 2, lambda: False):
                self.fail('Blocked domain reached')
        with Traffic(self.root).request('https://other.example/a', 2, lambda: False):
            pass

    def test_retry_after_and_cancellation(self):
        traffic = Traffic(self.root)
        for header, expected in [('120', 1120), ('Thu, 01 Jan 1970 00:20:00 GMT', 1200), ('invalid', 4600)]:
            with patch('espbs.traffic.time.time', return_value=1000):
                with self.assertRaises(SourceBlocked):
                    traffic.response('https://example.org/a', 429, header)
            self.assertEqual(traffic.status()[0]['blocked_until'], expected)
        with self.assertRaises(Stopped):
            with traffic.request('https://other.example/a', 2, lambda: True):
                self.fail('Cancelled request reached')

    def test_http_clients_persist_block_before_next_request(self):
        from espbs.eltex import Client
        from espbs.universal import Client as PublicClient
        response = MagicMock(status_code=403, headers={})
        response.__enter__.return_value = response
        client = Client(root=self.root)
        self.addCleanup(client.close)
        with patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(SourceBlocked):
                client.get('https://eltex.ru/robots.txt')
            with self.assertRaises(SourceBlocked):
                client.get('https://eltex.ru/product/a/')
            self.assertEqual(get.call_count, 1)
        public = PublicClient('https://example.org/', root=self.root)
        connection = MagicMock()
        connection.getresponse.return_value.status = 429
        connection.getresponse.return_value.getheader.return_value = '600'
        with patch('espbs.universal.public_addresses', return_value=['93.184.215.14']), patch('http.client.HTTPSConnection', return_value=connection):
            with self.assertRaises(SourceBlocked):
                public.get('https://example.org/a')
            with self.assertRaises(SourceBlocked):
                PublicClient('https://example.org/', root=self.root).get('https://example.org/b')
            self.assertEqual(connection.request.call_count, 1)
            connection.close.assert_called_once()

    def test_repeat_collection_updates_and_cleanup_preserves_newer_record(self):
        catalog = Catalog(self.root)
        product = {'source': 'example', 'source_url': 'https://example.org/a', 'name': 'Model', 'mpn': 'ABC'}
        identity = catalog.add(product, 'first')
        self.assertEqual(Catalog(self.root).add({**product, 'name': 'Updated'}, 'second'), identity)
        catalog.release('first')
        self.assertEqual(catalog.products()[0]['payload']['name'], 'Updated')
        self.assertEqual(len(catalog.products()), 1)
        # Identical MPN from an unverified second source must not merge.
        other = catalog.add({**product, 'source': 'other'}, 'third')
        self.assertNotEqual(other, identity)
        catalog.release('second')
        rows = {row['id']: row for row in catalog.products()}
        self.assertIsNone(rows[identity]['payload'])
        self.assertIsNotNone(rows[other]['payload'])
        self.assertEqual(catalog.add(product, 'fourth'), identity)

    def test_job_replay_repairs_catalog_before_checkpoint(self):
        from espbs.jobs import Job
        from test_jobs import FakeClient
        job = Job.create(self.root, 1)
        with patch.object(Catalog, 'add', side_effect=RuntimeError('interrupted')):
            self.assertEqual(job.run(FakeClient())['state'], 'FAILED')
        self.assertEqual(job.info()['completed'], 0)
        self.assertEqual(job.run(FakeClient())['state'], 'COMPLETED')
        second = Job.create(self.root, 1)
        self.assertEqual(second.run(FakeClient())['state'], 'COMPLETED')
        self.assertEqual(len(Catalog(self.root).products()), 1)
