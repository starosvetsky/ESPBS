"""Synthetic material extraction, field retention and explicit coverage."""
import json
import tempfile
import unittest
from unittest.mock import Mock
from espbs.materials import documents, coverage
from espbs.photos import extract, select
from espbs.directory import Directory, Enricher, model_code
from espbs.universal import Adapter
from espbs.jobs import Job
from espbs.storage import Batch


HTML = '<main><h1>Model X</h1><div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">Model X</h1><meta itemprop="brand" content="Alpha"><meta itemprop="mpn" content="X"><div class="gallery"><img alt="Model X" src="/x.jpg"></div><table><tr><td>Ports</td><td>8</td></tr></table><a href="https://files.example/manual x.pdf">Manual</a><a href="https://files.example/manual x.pdf">Download</a></div></main>'


class MaterialsTests(unittest.TestCase):
    def test_documents_scope_dedup_and_encoded_url(self):
        html = '<nav><a href="/promo.pdf">Promo</a></nav>' + HTML
        docs = documents(html, 'https://alpha.example/p')
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['url'], 'https://files.example/manual%20x.pdf')
        self.assertEqual(docs[0]['source_url'], 'https://alpha.example/p')

    def test_photo_and_forbidden_source(self):
        self.assertEqual(extract(HTML, 'https://alpha.example/p'), ['https://alpha.example/x.jpg'])
        self.assertEqual(extract(HTML, 'https://olnisa.ru/p'), [])

    def test_official_registry_and_job_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            Directory(root).save_manufacturer({'brand':'Alpha','home_url':'https://alpha.example/'})
            job = Job.create(root, 1, 'auto', 'https://alpha.example/p')
            client = Mock(); client.get.return_value = HTML
            result = job.run(client)
            self.assertEqual(result['state'], 'COMPLETED', result)
            self.assertEqual(result['coverage']['images'], 1)
            self.assertEqual(result['coverage']['documents'], 1)
            self.assertEqual(result['coverage']['description'], 0)
            product = json.loads(next(Batch(root, job.id).records())['payload'])
            self.assertEqual(product['coverage']['status'], 'PARTIAL')
            self.assertEqual(product['quality']['status'], 'REVIEW')

    def test_old_official_record_refreshes_materials_in_new_result(self):
        with tempfile.TemporaryDirectory() as root:
            Directory(root).save_manufacturer({'brand':'Alpha','home_url':'https://alpha.example/'})
            original = Adapter().product(HTML, 'https://alpha.example/p')
            original['documents'] = []
            enricher = Enricher(root); client = Mock(); client.get.return_value = HTML
            enricher.clients['alpha.example'] = client
            result = enricher.enrich(original)
            result = select(result, 'official', original)
            self.assertTrue(result['documents'])
            self.assertTrue(result['images'])
            self.assertEqual(original['documents'], [])
            self.assertEqual(result['enrichment']['status'], 'SOURCE_OFFICIAL')

    def test_empty_official_fields_do_not_erase_source(self):
        with tempfile.TemporaryDirectory() as root:
            Directory(root).save_manufacturer({'brand':'Alpha','home_url':'https://alpha.example/','template':'https://alpha.example/{mpn}'})
            original = Adapter().product(HTML, 'https://shop.example/p')
            original['description'] = 'Source description'
            enricher = Enricher(root); client = Mock()
            client.get.return_value = '<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'X','brand':'Alpha','mpn':'X'})+'</script>'
            enricher.clients['alpha.example'] = client
            result = enricher.enrich(original)
            self.assertEqual(result['description'], original['description'])
            self.assertEqual(result['documents'], original['documents'])
            self.assertEqual(result['attributes'], original['attributes'])

    def test_model_suffix_and_coverage(self):
        self.assertEqual(model_code('SMG500-REC (SMG500REC)'), 'SMG500-REC')
        self.assertEqual(model_code('MES2428_DC'), 'MES2428_DC')
        self.assertEqual(model_code('X (Y)'), 'X (Y)')
        self.assertEqual(len(coverage({})['missing']), 4)

    def test_model_suffix_is_not_a_complete_official_model(self):
        with tempfile.TemporaryDirectory() as root:
            Directory(root).save_mapping({'brand':'Eltex','mpn':'DC','url':'https://eltex.ru/product/example/'})
            original = {'source_url':'https://shop.example/p','manufacturer':'Eltex','mpn':'DC','attributes':{}}
            enricher = Enricher(root); client = Mock()
            client.get.return_value = '<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Коммутатор доступа MES2428_DC','brand':{'name':'Eltex'}})+'</script>'
            enricher.clients['eltex.ru'] = client
            self.assertEqual(enricher.enrich(original)['enrichment']['status'], 'UNVERIFIED')
