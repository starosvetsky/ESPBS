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
