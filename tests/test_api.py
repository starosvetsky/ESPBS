"""Loopback API tests use synthetic records and never contact manufacturers."""

import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from espbs.api import API
from espbs.archive import verify_archive
from espbs.jobs import Job
from espbs.storage import Batch


def record(number):
    return {'source': 'fixture', 'source_url': f'https://example.invalid/{number}',
            'external_id': str(number), 'name': f'Synthetic {number}',
            'quality': {'status': 'GOOD'}}


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = API(('127.0.0.1', 0), self.temp.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, method='GET', body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=3) as response:
            content = response.read()
            return response.status, json.loads(content) if content else None

    def test_storage_status(self):
        status, value = self.request('/api/storage')
        self.assertEqual(status, 200)
        self.assertGreater(value['reserve_bytes'], 0)
        self.assertIn('batches', value['sizes'])

    def test_archive_queue_start_stop_and_status(self):
        from espbs.archive_queue import run
        job = Job.create(self.temp.name, 1)
        Batch(self.temp.name, job.id).add(record(1))
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        with patch('espbs.archive_queue.subprocess.Popen') as popen:
            code, value = self.request(f'/api/jobs/{job.id}/archive-queue-start', 'POST', {})
            self.assertEqual(code, 202)
            self.assertEqual(value['state'], 'QUEUED')
            self.request(f'/api/jobs/{job.id}/archive-queue-start', 'POST', {})
            self.assertEqual(popen.call_count, 1)
        _, value = self.request(f'/api/jobs/{job.id}/archive-queue-stop', 'POST', {})
        self.assertEqual(value['stop'], 1)
        self.assertEqual(run(self.temp.name, job.id)['state'], 'STOPPED')
        with patch('espbs.archive_queue.subprocess.Popen'):
            self.request(f'/api/jobs/{job.id}/archive-queue-start', 'POST', {})
        run(self.temp.name, job.id)
        _, value = self.request(f'/api/jobs/{job.id}')
        self.assertEqual(value['archive_queue']['state'], 'COMPLETED')
        self.assertEqual(value['archive_queue']['last_seq'], 1)

    def test_archive_part_preserves_parent_and_can_be_exported(self):
        job = Job.create(self.temp.name, 1)
        batch = Batch(self.temp.name, job.id)
        batch.add(record(1))
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        route = f'/api/jobs/{job.id}/archive-part'
        code, child = self.request(route, 'POST', {'after': ''})
        self.assertEqual(code, 201)
        self.assertEqual(child['source'], 'archive-part')
        self.assertEqual(child['completed'], 1)
        _, repeated = self.request(route, 'POST', {'after': ''})
        self.assertEqual(child['id'], repeated['id'])
        _, parent = self.request(f'/api/jobs/{job.id}')
        self.assertTrue(parent['archive_parts']['done'])
        self.assertEqual(batch.info()['record_count'], 1)
        code, archive = self.request(f"/api/jobs/{child['id']}/archive", 'POST', {})
        self.assertEqual(code, 201)
        self.assertTrue(archive['ready'])

    def test_attachment_export_is_queued_and_visible_without_blocking_http(self):
        from espbs.export_tasks import run
        job = Job.create(self.temp.name, 1)
        Batch(self.temp.name, job.id).add(record(1))
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        url = f'/api/jobs/{job.id}/archive'
        with patch('espbs.export_tasks.subprocess.Popen') as popen:
            code, value = self.request(url, 'POST', {'include_files': True})
            self.assertEqual(code, 202)
            self.assertEqual(value['task']['state'], 'QUEUED')
            self.request(url, 'POST', {'include_files': True})
            self.assertEqual(popen.call_count, 1)
        _, job_info = self.request(f'/api/jobs/{job.id}')
        self.assertEqual(job_info['archive']['task']['state'], 'QUEUED')
        with self.assertRaises(HTTPError) as error:
            self.request(url, 'POST', {})
        self.assertEqual(error.exception.code, 400)
        run(self.temp.name, job.id)
        _, job_info = self.request(f'/api/jobs/{job.id}')
        self.assertTrue(job_info['archive']['ready'])
        self.assertEqual(job_info['archive']['attachments'], 'embedded-with-report')
        self.assertEqual(job_info['archive']['attachment_summary']['unique_files'], 0)
        with self.assertRaises(HTTPError):
            self.request(url, 'POST', {'include_files': 'yes'})

    def test_inventory_includes_legacy_batches_search_and_cleanup(self):
        first, second = Batch.create(self.temp.name), Batch.create(self.temp.name)
        first.add({**record(1), 'name': 'Сетевой коммутатор <script>'})
        second.add(record(2))
        _, summary = self.request('/api/inventory/batches')
        self.assertEqual(summary['record_count'], 2)
        _, page = self.request('/api/inventory/products?limit=1')
        self.assertTrue(page['has_more'])
        _, next_page = self.request('/api/inventory/products?limit=1&after=' + page['next_cursor'])
        self.assertFalse(next_page['has_more'])
        self.assertNotEqual(page['products'][0]['cursor'], next_page['products'][0]['cursor'])
        from urllib.parse import quote
        _, found = self.request('/api/inventory/products?q=' + quote('СЕТЕВОЙ'))
        self.assertEqual(found['products'][0]['batch_id'], first.id)
        _, filtered = self.request('/api/inventory/products?batch=' + second.id)
        self.assertEqual(len(filtered['products']), 1)
        with first.connection() as db:
            db.execute('DELETE FROM records')
        _, summary = self.request('/api/inventory/batches')
        self.assertEqual(summary['record_count'], 1)
        _, found = self.request('/api/inventory/products?q=' + quote('СЕТЕВОЙ'))
        self.assertEqual(found['products'], [])
        for query in ('limit=0', 'limit=101', 'after=bad', 'batch=../../other'):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/inventory/products?' + query)
            self.assertEqual(error.exception.code, 400)
        with urlopen(self.base + '/inventory.html') as response:
            self.assertIn('inventory.js', response.read().decode())

    def test_catalog_paging_and_traffic_status(self):
        from espbs.catalog import Catalog
        from espbs.traffic import Traffic, SourceBlocked
        catalog = Catalog(self.temp.name)
        catalog.add(record(1), 'first')
        catalog.add(record(2), 'second')
        _, first = self.request('/api/catalog?limit=1')
        _, second = self.request('/api/catalog?limit=1&after=' + first['next_cursor'])
        self.assertNotEqual(first['products'][0]['id'], second['products'][0]['id'])
        _, empty = self.request('/api/catalog?after=' + second['next_cursor'])
        self.assertEqual(empty['products'], [])
        with self.assertRaises(HTTPError) as error:
            self.request('/api/catalog?limit=101')
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(SourceBlocked):
            Traffic(self.temp.name).response('https://example.org/a', 403)
        _, value = self.request('/api/traffic')
        self.assertEqual(value['domains'][0]['reason'], 'HTTP 403')

    @patch('espbs.api.launch_worker')
    def test_create_list_and_actions(self, launch):
        status, created = self.request('/api/jobs', 'POST', {'source': 'eltex', 'limit': 2})
        self.assertEqual(status, 202)
        launch.assert_called_once_with(self.server.root, created['id'])
        _, listing = self.request('/api/jobs')
        self.assertEqual(listing['jobs'][0]['id'], created['id'])
        _, stopped = self.request(f"/api/jobs/{created['id']}/stop", 'POST', {})
        self.assertEqual(stopped['stop'], 1)
        self.request(f"/api/jobs/{created['id']}/resume", 'POST', {})
        self.assertEqual(launch.call_count, 2)

    def test_event_cursor_and_product_page(self):
        job = Job.create(self.temp.name, 3)
        batch = Batch(self.temp.name, job.id)
        for number in range(3):
            batch.add(record(number))
            job.event('saved', {'number': number}, None)
        _, first = self.request(f'/api/jobs/{job.id}/events?after=0&limit=2')
        self.assertEqual([item['number'] for item in first['events']], [0, 1])
        _, second = self.request(
            f"/api/jobs/{job.id}/events?after={first['next_cursor']}&limit=2")
        self.assertEqual([item['number'] for item in second['events']], [2])
        _, products = self.request(f'/api/jobs/{job.id}/products?limit=2')
        self.assertEqual(len(products['products']), 2)
        _, remaining = self.request(
            f"/api/jobs/{job.id}/products?after={products['next_cursor']}&limit=2")
        self.assertEqual(len(remaining['products']), 1)

    @patch('espbs.api.launch_worker')
    def test_source_registry_and_olnisa_configuration(self, launch):
        _, registry = self.request('/api/sources')
        self.assertEqual({x['id'] for x in registry['sources']}, {'eltex', 'olnisa'})
        status, created = self.request('/api/jobs', 'POST', {
            'source': 'olnisa', 'limit': 1,
            'start_url': 'https://olnisa.ru/manufacturers/eltex/mes2428/',
            'enrichment': 'eltex'})
        self.assertEqual(status, 202)
        self.assertEqual(created['source'], 'olnisa')
        self.assertEqual(created['enrichment'], 'eltex')
        _, saved = self.request('/api/jobs/' + created['id'])
        self.assertEqual(saved['start_url'], created['start_url'])
        with self.assertRaises(HTTPError):
            self.request('/api/jobs', 'POST', {'source': 'olnisa', 'start_url': 'https://example.invalid/'})
        self.assertEqual(launch.call_count, 1)

    def test_orphaned_running_state_is_failed(self):
        job = Job.create(self.temp.name, 1)
        with job.db() as db:
            db.execute("UPDATE job SET state='RUNNING'")
        _, value = self.request(f'/api/jobs/{job.id}')
        self.assertEqual(value['state'], 'FAILED')
        self.assertIn('no longer running', value['error'])

    def test_prepare_and_download_archive(self):
        job = Job.create(self.temp.name, 1)
        Batch(self.temp.name, job.id).add(record(1))
        with job.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        status, archive = self.request(f'/api/jobs/{job.id}/archive', 'POST', {})
        self.assertEqual(status, 201)
        self.assertTrue(archive['ready'])
        self.assertEqual(archive['record_count'], 1)
        _, detail = self.request(f'/api/jobs/{job.id}')
        self.assertTrue(detail['archive']['ready'])
        with urlopen(self.base + f'/api/jobs/{job.id}/archive', timeout=3) as response:
            self.assertEqual(response.headers['Content-Type'], 'application/zip')
            downloaded = self.server.root / 'downloaded.zip'
            downloaded.write_bytes(response.read())
        self.assertEqual(verify_archive(downloaded)['record_count'], 1)

    def test_validation_and_dashboard(self):
        with urlopen(self.base + '/', timeout=3) as response:
            self.assertIn(b'COLLECTION CONTROL', response.read())
        with urlopen(self.base + '/favicon.svg', timeout=3) as response:
            self.assertEqual(response.headers['Content-Type'], 'image/svg+xml')
        with self.assertRaises(HTTPError) as error:
            self.request('/api/jobs', 'POST', {'source': 'other', 'limit': 2})
        self.assertEqual(error.exception.code, 400)

    @patch('espbs.api.launch_worker')
    def test_directory_and_separate_enrichment_api(self, launch):
        _, directory = self.request('/api/directory')
        self.assertEqual({m['brand'] for m in directory['manufacturers']}, {'Eltex', 'D-Link', 'QTECH', 'OSTEC'})
        self.request('/api/manufacturers', 'POST', {'brand':'Synthetic','home_url':'https://maker.example/'})
        self.request('/api/mappings', 'POST', {'brand':'Synthetic','mpn':'S-1','url':'https://maker.example/s1'})
        _, directory = self.request('/api/directory')
        self.assertEqual(directory['mappings'][0]['mpn'], 's-1')
        parent = Job.create(self.temp.name, 1)
        Batch(self.temp.name,parent.id).add(record(1))
        with parent.db() as db:
            db.execute("UPDATE job SET state='COMPLETED'")
        status, child = self.request('/api/jobs/'+parent.id+'/enrich','POST',{})
        self.assertEqual(status,202)
        self.assertEqual(child['source'],'enrichment')
        self.assertEqual(child['parent_id'],parent.id)
        launch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
