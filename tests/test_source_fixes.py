import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from espbs.robots import Robots
from espbs.universal import Client, Redirect, Adapter, normalize_input
from espbs.directory import Directory, detect
from espbs.jobs import Job
from espbs.storage import Batch
from espbs.photos import extract, select


def html(image):
    return '<script type="application/ld+json">' + json.dumps({
        '@type': 'Product', 'name': 'Alpha X1', 'brand': 'Alpha', 'mpn': 'X1',
        'image': image, 'description': 'Specifications'}) + '</script>'


class SourceFixTests(unittest.TestCase):
    def test_olnisa_query_pages_do_not_hide_available_categories(self):
        from espbs import olnisa
        page = '<ul class="cat-menu"><li><a href="/manufacturers/dkc/cables/">Cables</a></li></ul><a class="page_link" href="/manufacturers/dkc/page-2/?filter=1">2</a>'
        links, pages = olnisa.listing(page, 'https://olnisa.ru/manufacturers/dkc/')
        self.assertEqual(links, [])
        self.assertEqual(pages, ['https://olnisa.ru/manufacturers/dkc/cables/'])
        self.assertTrue(olnisa.discovery_warning(page))

    def test_robots_groups_query_and_allow_precedence(self):
        robots = Robots()
        robots.parse('User-agent: *\nDisallow: /?\nDisallow: /uploads/\nAllow: /uploads/*.pdf$\nUser-agent: OtherBot\nDisallow: /'.splitlines())
        self.assertTrue(robots.can_fetch('ESPBS/0.2', 'https://shop.nag.ru/catalog/test'))
        self.assertFalse(robots.can_fetch('ESPBS/0.2', 'https://shop.nag.ru/?x=1'))
        self.assertTrue(robots.can_fetch('ESPBS/0.2', 'https://shop.nag.ru/uploads/manual.pdf'))
        self.assertFalse(robots.can_fetch('ESPBS/0.2', 'https://shop.nag.ru/uploads/manual.zip'))
        self.assertFalse(robots.can_fetch('OtherBot', 'https://shop.nag.ru/catalog/test'))

    def test_redirect_checks_destination_robots(self):
        client = Client('https://shop.example/')
        with patch.object(client, '_request', side_effect=['User-agent: *\nDisallow: /private', Redirect('https://shop.example/private')]) as request:
            with self.assertRaisesRegex(ValueError, 'robots'):
                client.get('https://shop.example/start')
            self.assertEqual(request.call_count, 2)
        client = Client('https://shop.example/')
        with patch.object(client, '_request', side_effect=['User-agent: *', Redirect('https://shop.example/end'), 'done']):
            self.assertEqual(client.get('https://shop.example/start'), 'done')
            self.assertEqual(client.last_url, 'https://shop.example/end')
        client = Client('https://shop.example/')
        with patch.object(client, '_request', side_effect=['User-agent: *', Redirect('https://127.0.0.1/')]):
            with self.assertRaises(ValueError):
                client.get('https://shop.example/start')

    def test_normalization_retains_functional_parameters(self):
        self.assertEqual(normalize_input('https://shop.nag.ru/catalog/x?ysclid=abc&page=2&utm_source=y'), 'https://shop.nag.ru/catalog/x?page=2')
        with tempfile.TemporaryDirectory() as root:
            value = detect(root, 'https://olnisa.ru/manufacturers/eaton')
            self.assertEqual(value['source'], 'olnisa')
            self.assertTrue(value['start_url'].endswith('/eaton/'))
        with self.assertRaisesRegex(ValueError, 'две ссылки'):
            normalize_input('https://example.com/path/https://example.com/path/')

    def test_html_catalog_and_product_are_distinct(self):
        adapter = Adapter()
        urls, pages = adapter.listing('<h1>Catalog</h1><div class="product-wrapper"><a href="/ru/products/1/2697.html">DMS</a></div>', 'https://dlink.ru/ru/products/1/')
        self.assertEqual(urls, ['https://dlink.ru/ru/products/1/2697.html'])
        raw = '<h2>DMS-3130-30PS</h2><h1>Warning</h1><div class="sub-content-block table"><table><tr><td>Ports</td><td>24</td></tr></table></div>'
        product = adapter.product(raw, urls[0])
        self.assertEqual(product['mpn'], 'DMS-3130-30PS')
        self.assertEqual(product['attributes'], {'Ports': ['24']})
        urls, pages = adapter.listing('<h3 class="product-category__title"><a href="/catalog/switches/access/">Access</a></h3>', 'https://www.qtech.ru/catalog/switches/')
        self.assertEqual(urls, [])
        self.assertEqual(pages, ['https://www.qtech.ru/catalog/switches/access/'])
        with self.assertRaises(ValueError):
            adapter.product('<h1>Some category</h1>', 'https://unknown.example/category/')

    def test_photos_persist_through_separate_enrichment(self):
        with tempfile.TemporaryDirectory() as root:
            Directory(root).save_manufacturer({'brand': 'Alpha', 'home_url': 'https://alpha.example/', 'template': 'https://alpha.example/{mpn}'})
            for policy, source_image, expected in [
                ('store', '/store.jpg', ['https://shop.example/store.jpg']),
                ('official', '/store.jpg', ['https://alpha.example/official.jpg']),
                ('fallback', '/store.jpg', ['https://shop.example/store.jpg']),
                ('fallback', '', ['https://alpha.example/official.jpg']),
                ('store', '', []), ('none', '/store.jpg', [])]:
                parent = Job.create(root, 1, 'auto', 'https://shop.example/p', photo_policy=policy)
                client = Mock(); client.get.return_value = html(source_image)
                self.assertEqual(parent.run(client)['state'], 'COMPLETED')
                child = Job.create_enrichment(parent)
                with patch('espbs.directory.Client') as factory:
                    factory.return_value.get.return_value = html('/official.jpg')
                    self.assertEqual(child.run()['state'], 'COMPLETED')
                result = json.loads(next(Batch(root, child.id).records())['payload'])
                self.assertEqual(result['images'], expected, policy)

    def test_forbidden_and_missing_official_photos(self):
        self.assertEqual(extract(html('/photo.jpg'), 'https://olnisa.ru/manufacturers/x/p/'), [])
        original = {'source_url': 'https://olnisa.ru/manufacturers/x/p/', 'images': ['https://olnisa.ru/photo.jpg']}
        result = {'images': ['https://official.example/p.jpg'], 'enrichment': {'status': 'MATCHED', 'source_url': 'https://official.example/p'}}
        self.assertEqual(select(result.copy(), 'store', original)['images'], [])
        self.assertEqual(select(result.copy(), 'fallback', original)['images'], ['https://official.example/p.jpg'])
        original = {'source_url': 'https://shop.example/p', 'images': ['/photo.jpg']}
        failed = {'images': [], 'enrichment': {'status': 'NO_MANUFACTURER'}}
        self.assertEqual(select(failed, 'fallback', original)['images'], ['https://shop.example/photo.jpg'])


if __name__ == '__main__':
    unittest.main()
