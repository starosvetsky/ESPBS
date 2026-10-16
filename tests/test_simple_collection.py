"""Synthetic regression checks: pagination, unlimited jobs and photo policy."""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from espbs import olnisa
from espbs.directory import Directory, Enricher
from espbs.jobs import Job
from espbs.storage import Batch


class SimpleCollectionTests(unittest.TestCase):
    def test_nested_category_pagination_stays_in_selected_category(self):
        category = 'https://olnisa.ru/manufacturers/eltex/network/switches/'
        card = category + 'MES2428/'
        html = f'<a class="catalog-item" href="{card}">x</a>'
        html += '<a class="catalog-item" href="/manufacturers/eltex/mes2424b/">root card</a>'
        html += '<a class="catalog-item" href="?tracking=1">ignore</a>'
        html += '<a class="catalog-item" href="/manufacturers/other/card/">ignore</a>'
        for href in (category+'page-2/', category+'page-3/', olnisa.CATALOG+'page-2/',
                     olnisa.CATALOG+'network/routers/page-2/', category+'page-0/'):
            html += f'<a class="page_link" href="{href}">page</a>'
        for current in (category, category+'page-2/'):
            links, pages = olnisa.listing(html, current)
            self.assertEqual(links, [card, olnisa.CATALOG+'mes2424b/'])
            self.assertEqual(pages, [category+'page-2/', category+'page-3/'])

    def test_nested_url_guards(self):
        from espbs.sources import configuration
        url = olnisa.CATALOG+'network/switches/'
        self.assertEqual(configuration('olnisa', url)['start_url'], url)
        for bad in (url+'?page=2', url+'#section', url.replace('https:', 'http:'),
                    url.replace('olnisa.ru', 'olnisa.ru.evil.invalid'),
                    olnisa.CATALOG+'network/%2Fother/'):
            with self.assertRaises(ValueError):
                configuration('olnisa', bad)

    def test_nested_category_job_resume_visits_second_page(self):
        from test_sources import HTML
        category = olnisa.CATALOG + 'network/switches/'
        first, second = category+'MES2428/', category+'MES2424/'
        responses = {
            category: f'<a class="catalog-item" href="{first}">1</a>'
                      f'<a class="page_link" href="{category}page-2/">2</a>',
            category+'page-2/': f'<a class="catalog-item" href="{second}">2</a>',
            first: HTML, second: HTML.replace('MES2428', 'MES2424')}
        with tempfile.TemporaryDirectory() as root:
            job = Job.create(root, None, 'olnisa', category, 'none')
            client = Mock()
            client.get.side_effect = responses.__getitem__
            stopped = job.run(client, lambda e: job.stop() if e['kind']=='saved' else None)
            self.assertEqual(stopped['state'], 'STOPPED')
            self.assertEqual(stopped['completed'], 1)
            client.reset_mock()
            result = Job(root, job.id).run(client)
            self.assertEqual(result['state'], 'COMPLETED')
            self.assertEqual(result['completed'], 2)
            client.get.assert_called_once_with(second)

    def test_path_pagination_and_uppercase_card(self):
        html = '<a class="catalog-item" href="/manufacturers/eltex/FF718A57/">x</a>'
        html += '<a class="page_link" href="/manufacturers/eltex/page-2/">2</a>'
        html += '<a class="page_link" href="/manufacturers/other/page-2/">bad</a>'
        html += '<a class="page_link" href="?page=2">blocked</a>'
        links, pages = olnisa.listing(html, olnisa.CATALOG)
        self.assertEqual(links, [olnisa.CATALOG + 'FF718A57/'])
        self.assertEqual(pages, [olnisa.CATALOG + 'page-2/'])

    def test_unlimited_collection_crosses_queue_window(self):
        with tempfile.TemporaryDirectory() as root:
            job = Job.create(root, None, 'auto', 'https://shop.example/catalog',
                             selectors={'product_links':'a.product','next_links':'a.next'}, photo_policy='none')
            client = Mock()
            def get(url):
                if '/product/' in url:
                    return '<script type="application/ld+json">' + json.dumps({
                        '@type':'Product','name':url,'brand':'Alpha','mpn':url,
                        'image':'https://shop.example/photo.png'}) + '</script>'
                start = 500 if url.endswith('/page2') else 0
                return ''.join(f'<a class="product" href="/product/{i}">x</a>' for i in range(start,start+500)) + (
                    '<a class="next" href="/page2">Next</a>' if start == 0 else '')
            client.get.side_effect = get
            result = job.run(client)
            self.assertEqual(result['state'], 'COMPLETED')
            self.assertEqual(result['completed'], 1000)
            self.assertIsNone(result['target'])
            self.assertTrue(all(not json.loads(r['payload'])['images'] for r in Batch(root, job.id).records()))
            child = Job.create_enrichment(job)
            self.assertEqual(child.info()['photo_policy'], 'none')

    def test_sitemap_discovery_never_merges_suffix_variant(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Directory(root)
            directory.save_manufacturer({'brand':'Alpha','home_url':'https://alpha.example/'})
            enricher = Enricher(root)
            client = Mock()
            client.get.side_effect = ['Sitemap: https://alpha.example/map.xml',
                '<urlset><url><loc>https://alpha.example/product/X-1</loc></url></urlset>',
                '<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Other',
                    'brand':'Alpha','mpn':'X-1_DC'})+'</script>']
            original = {'source_url':'https://shop.example/p','manufacturer':'Alpha','mpn':'X-1',
                        'attributes':{},'images':[]}
            with patch.object(enricher,'client',return_value=client):
                result = enricher.enrich(original)
            self.assertEqual(result['enrichment']['status'], 'MISMATCH')
            self.assertEqual(result['images'], [])


if __name__ == '__main__':
    unittest.main()
