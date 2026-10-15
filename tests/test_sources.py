"""Synthetic site-shaped fixtures; live verification is documented separately."""
import json
import tempfile
import unittest
from unittest.mock import Mock

from espbs import olnisa
from espbs.archive import export_batch, verify_archive
from espbs.jobs import Job
from espbs.sources import ALIASES, configuration, enrich
from espbs.storage import Batch

URL = olnisa.CATALOG + 'mes2428/'
HTML = '''<div class="catalog-detail-mini-params"><h1>MES2428 Eltex</h1>
<div class="catalog-detail-mini-params-grid">
<span class="title">Производитель</span><span>Eltex</span>
<span class="title">Артикул</span><span>MES2428</span>
<span class="title">Наличие</span><span>от 1 недели</span></div></div>
<div class="catalog-detail-price-block"><span class="normal-price">под заказ</span></div>
<div itemprop="description">Synthetic store description</div>
<img src="https://olnisa.ru/forbidden.jpg">
<a class="catalog-item" href="/manufacturers/eltex/wrong-related/">Related</a>'''
OFFICIAL = '<script type="application/ld+json">' + json.dumps({
    '@type': 'Product', 'name': 'Коммутатор доступа MES2428',
    'brand': {'name': 'Eltex'}, 'description': 'Synthetic official description',
    'image': ['/test.png', 'https://olnisa.ru/forbidden.jpg'],
    'additionalProperty': [{'name': 'Ports', 'value': '24'}]}) + '</script>'


class SourceTests(unittest.TestCase):
    def test_scope_and_product(self):
        for url in ['https://evil.invalid/', 'https://olnisa.ru@evil.invalid/',
                    olnisa.CATALOG+'?page=2', 'https://olnisa.ru/manufacturers/other/']:
            with self.assertRaises(ValueError):
                configuration('olnisa', url)
        self.assertEqual(olnisa.listing(HTML, URL), ([URL], []))
        item = olnisa.product(HTML, URL)
        self.assertEqual(item['mpn'], 'MES2428')
        self.assertEqual(item['offer']['price_text'], 'под заказ')
        self.assertEqual(item['images'], [])
        self.assertNotIn('forbidden', json.dumps(item))

    def test_match_provenance_and_no_fuzzy_merge(self):
        client = Mock(); client.get.return_value = OFFICIAL
        item = olnisa.product(HTML, URL)
        result = enrich(item, client)
        self.assertEqual(result['enrichment']['status'], 'MATCHED')
        self.assertEqual(result['images'], ['https://eltex.ru/test.png'])
        self.assertEqual(result['offer'], item['offer'])
        self.assertEqual(result['provenance']['original_description'], item['description'])
        self.assertEqual(result['attributes'], {'Ports': ['24']})
        for brand, mpn in [('Eltex','MES2428_DC'), ('Other','MES2428'), ('Eltex','MES2428B')]:
            candidate = {**item, 'manufacturer': brand, 'mpn': mpn}
            result = enrich(candidate, client)
            self.assertNotEqual(result['enrichment']['status'], 'MATCHED')
            self.assertEqual(result['images'], [])
        self.assertEqual(item['description'], 'Synthetic store description')

    def test_official_failure_preserves_offer(self):
        client = Mock(); client.get.side_effect = RuntimeError('HTTP 429')
        item = olnisa.product(HTML, URL)
        result = enrich(item, client)
        self.assertEqual(result['enrichment']['status'], 'ERROR')
        self.assertEqual(result['offer'], item['offer'])
        self.assertEqual(result['quality']['status'], 'REVIEW')

    def test_job_resume_configuration_and_export(self):
        with tempfile.TemporaryDirectory() as root:
            job = Job.create(root, 1, 'olnisa', URL, 'eltex')
            store = Mock(); store.get.return_value = HTML
            official = Mock(); official.get.return_value = OFFICIAL
            result = job.run(store, lambda e: job.stop() if e['kind']=='discovered' else None,
                             official_client=official)
            self.assertEqual(result['state'], 'STOPPED')
            resumed = Job(root, job.id)
            self.assertEqual(resumed.info()['start_url'], URL)
            result = resumed.run(store, official_client=official)
            self.assertEqual(result['state'], 'COMPLETED')
            item = Batch(root, job.id).products()[0]['product']
            self.assertEqual(item['enrichment']['status'], 'MATCHED')
            path = export_batch(Batch(root,job.id), root+'/exports')
            self.assertEqual(verify_archive(path)['record_count'], 1)

    def test_old_job_without_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            job = Job.create(root, 1)
            with job.db() as db:
                db.execute('DROP TABLE config')
            self.assertEqual(job.info()['source'], 'eltex')


if __name__ == '__main__':
    unittest.main()
