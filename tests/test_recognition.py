"""Synthetic different-site layouts, including an OSTEC-like table of div rows."""
import json
import unittest
from espbs.universal import Adapter


def ld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj) + '</script>'


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Adapter()
        self.url = 'https://example.org/catalog/'

    def test_div_rows_any_domain_and_bitrix_paging(self):
        html = '<h1>Без перфорации</h1><div>' + ''.join(
            f'<div class="row element-item"><a href="/catalog/{i}/"><img src="/{i}.jpg"></a>'
            f'<div><a href="/catalog/{i}/">Артикул-{i}</a></div><div>1 200,50 руб.</div>'
            '<a href="/order-sheet/">В корзине</a></div>' for i in (1, 2, 3)) + '</div>'
        html += '<a href="?PAGEN_1=2">2</a><a href="?PAGEN_1=2&sort=price">sort</a>'
        for host in ('example.org', 'another.example'):
            url = self.url.replace('example.org', host)
            links, pages = self.adapter.listing(html, url)
            self.assertEqual(links, [f'https://{host}/catalog/{i}/' for i in (1, 2, 3)])
            self.assertEqual(pages, [url + '?PAGEN_1=2'])
        with self.assertRaises(ValueError):
            self.adapter.product(html, self.url)

    def test_table_without_prices(self):
        html = '<table><tr><th>Артикул</th><th>Наименование</th></tr>' + ''.join(
            f'<tr><td>X{i}</td><td><a href="/goods/{i}">Cable {i}</a></td></tr>' for i in (1, 2)) + '</table>'
        self.assertEqual(len(self.adapter.listing(html, self.url)[0]), 2)

    def test_repeated_cards_and_navigation_exclusion(self):
        html = '<nav><a href="/login">Login</a></nav><section>' + ''.join(
            f'<article class="catalog-item"><img src="/a.png"><a href="/p/{i}">Model {i}</a></article>'
            for i in (1, 2)) + '</section><footer><a href="?page=30">30</a></footer>'
        links, pages = self.adapter.listing(html, self.url)
        self.assertEqual(len(links), 2)
        self.assertEqual(pages, [])

    def test_bitrix_catalog_section_items_without_numeric_price(self):
        html = '<main class="wrapper compact-breadcrumbs-N">' + ''.join(
            '<div class="catalog-section-item" data-role="item">'
            '<div class="catalog-section-item-image"><img src="/missing.png"></div>'
            f'<div class="catalog-section-item-name"><a href="/catalog/model-{i}/">Model {i}</a></div>'
            '<div class="catalog-section-item-price">Цена по запросу</div></div>'
            for i in (1, 2, 3)) + '</main>'
        self.assertEqual(self.adapter.listing(html, self.url)[0], [
            f'https://example.org/catalog/model-{i}/' for i in (1, 2, 3)])

    def test_bitrix_cards_in_separate_layout_wrappers(self):
        """Bitrix themes may give every marked card a different direct parent."""
        html = '<main>' + ''.join(
            '<div class="layout-cell">'
            '<div class="catalog_item_wrapp catalog_item item_wrap product_image" '
            f'id="bx_item_{item}">'
            f'<a href="/catalog/cables/model/{item}/"><img src="/{item}.jpg"></a>'
            f'<a href="/catalog/cables/model/{item}/">Cable {item}</a>'
            f'<span class="price">{item} 200 ₽ /шт</span>'
            '<a href="/basket/">В корзину</a>'
            '</div></div>' for item in (4374332, 4374333, 4374334))
        html += '<a href="?PAGEN_1=2">2</a><a href="?PAGEN_1=214">214</a></main>'
        links, pages = self.adapter.listing(html, self.url)
        self.assertEqual(links, [
            f'https://example.org/catalog/cables/model/{item}/'
            for item in (4374332, 4374333, 4374334)])
        self.assertEqual(pages, [self.url + '?PAGEN_1=2', self.url + '?PAGEN_1=214'])

    def test_real_breadcrumb_and_recommendation_blocks_are_excluded(self):
        html = '''
        <div class="breadcrumbs"><a href="/catalog/wrong">Catalog</a></div>
        <div class="recommendations"><div class="product-card">
          <img src="/wrong.jpg"><a href="/product/wrong">Wrong</a><b>100 ₽</b>
        </div></div>
        <main>''' + ''.join(
            f'<div class="product-card"><img src="/{item}.jpg">'
            f'<a href="/product/{item}">Item {item}</a><b>{item} ₽</b></div>'
            for item in (1, 2)) + '</main>'
        self.assertEqual(self.adapter.listing(html, self.url)[0], [
            'https://example.org/product/1', 'https://example.org/product/2'])

    def test_itemlist_without_product_schema_and_breadcrumbs(self):
        html = ld({'@type': 'ItemList', 'itemListElement': [
            {'@type': 'ListItem', 'item': {'url': '/p/1'}},
            {'@type': 'ListItem', 'url': '/p/2'},
            {'@type': 'ListItem', 'url': 'https://other.example/p'},
            {'@type': 'ListItem', 'url': '/cart?action=add'}]})
        self.assertEqual(self.adapter.listing(html, self.url)[0], ['https://example.org/p/1', 'https://example.org/p/2'])
        with self.assertRaisesRegex(ValueError, 'Структура страницы'):
            self.adapter.listing(html.replace('ItemList', 'BreadcrumbList'), self.url)

    def test_microdata_fields_sku_not_mpn_and_attributes(self):
        html = '<nav><span itemprop="name">Catalog</span></nav><div itemscope itemtype="https://schema.org/Product">'
        html += '<h1 itemprop="name">Cable tray</h1><div class="row"><div>Артикул</div><div>ABC-1</div></div>'
        html += '<div class="row"><div>Высота, мм</div><div>50</div></div><meta itemprop="price" content="1200"><meta itemprop="priceCurrency" content="RUB">'
        html += '<div itemprop="aggregateRating"><span>4.5</span><span>11</span></div></div>'
        product = self.adapter.product(html, self.url + '1')
        self.assertEqual(product['sku'], 'ABC-1')
        self.assertEqual(product['mpn'], '')
        self.assertEqual(product['attributes']['Высота, мм'], ['50'])
        self.assertNotIn('4.5', product['attributes'])
        self.assertEqual(product['offer']['price_text'], '1200')
        self.assertEqual(product['provenance']['recognition'], 'microdata')

    def test_plain_detail_requires_identity_and_facts(self):
        html = '<main><h1>Cable X</h1><dl><dt>MPN</dt><dd>X-1</dd><dt>Brand</dt><dd>Alpha</dd><dt>Length</dt><dd>3 m</dd></dl></main>'
        product = self.adapter.product(html, self.url + '1')
        self.assertEqual(product['mpn'], 'X-1')
        self.assertEqual(product['manufacturer'], 'Alpha')
        self.assertEqual(product['quality']['status'], 'REVIEW')
        self.assertEqual(self.adapter.listing(html, self.url + '1'), ([self.url + '1'], []))
        for fragment in ('<h1>Category</h1>', '<h1>Discount</h1><p>100 руб.</p>', '<h1>App</h1><script>loadProducts()</script>'):
            with self.assertRaisesRegex(ValueError, 'Структура страницы'):
                self.adapter.listing(fragment, self.url)

    def test_primary_card_ignores_recommendations(self):
        primary = ld({'@type': 'Product', 'name': 'Primary', 'mpn': 'P'})
        related = ''.join(f'<div class="product-card"><a href="/p/{i}">Other</a>100 руб.</div>' for i in (2, 3))
        self.assertEqual(self.adapter.listing(primary + related, self.url + '1'), ([self.url + '1'], []))

    def test_nested_main_entity_and_full_schema_type(self):
        html = ld({'@type': 'WebPage', 'mainEntity': {'@type': 'https://schema.org/Product', 'name': 'Main'}})
        self.assertEqual(self.adapter.product(html, self.url)['name'], 'Main')

    def test_category_with_one_structured_product_is_not_that_product(self):
        html = '<h1>Catalog</h1>' + ld({'@type': 'Product', 'name': 'Only item', 'url': '/p/1'})
        self.assertEqual(self.adapter.listing(html, self.url)[0], ['https://example.org/p/1'])
        with self.assertRaisesRegex(ValueError, 'другой странице'):
            self.adapter.product(html, self.url)

    def test_pagination_preserves_filters(self):
        html = '<a class="product-card" href="/p/1">One</a><a href="?color=red&page=2">2</a><a href="?page=3">3</a><a href="?color=red&page=4&action=buy">Buy</a>'
        self.assertEqual(self.adapter.listing(html, self.url + '?color=red')[1], [self.url + '?color=red&page=2'])

    def test_news_without_product_evidence_rejected(self):
        html = '<h1>News</h1><section><article><a href="/news/1">Report</a></article><article><a href="/news/2">Story</a></article></section>'
        with self.assertRaises(ValueError):
            self.adapter.listing(html, self.url)

    def test_content_child_categories_are_crawled_but_global_menu_is_not(self):
        html = '''
        <header><ul class="category-children-list"><li><a href="/catalog/wrong">Wrong</a></li></ul></header>
        <main>
          <section><ul class="category-children-list">
            <li><a href="/catalog/switches">Switches</a></li>
            <li><a href="/catalog/cables">Cables</a></li>
          </ul></section>
          <div class="product-card"><img src="/one.jpg"><a href="/products/one">One</a></div>
          <div class="product-card"><img src="/two.jpg"><a href="/products/two">Two</a></div>
        </main>'''
        links, pages = self.adapter.listing(html, self.url)
        self.assertEqual(links, ['https://example.org/products/one', 'https://example.org/products/two'])
        self.assertEqual(pages, ['https://example.org/catalog/switches',
                                 'https://example.org/catalog/cables'])
