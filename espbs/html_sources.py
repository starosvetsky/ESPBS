"""Explicit HTML recognition for verified source layouts and schema microdata."""
import re
from urllib.parse import urlsplit


def text(node):
    return (node.get('content') or node.get('href') or node.get_text(' ', strip=True)) if node else ''


def product(soup, url):
    host, path = urlsplit(url).hostname, urlsplit(url).path
    brand, heading, mpn = '', None, ''
    if host == 'dlink.ru' and re.fullmatch(r'/ru/products/\d+/\d+\.html', path):
        heading, brand = soup.select_one('h2'), 'D-Link'
    elif host == 'www.qtech.ru' and re.fullmatch(r'/catalog/switches/[^/]+/[^/]+/[^/]+/', path):
        heading, brand = soup.select_one('h1'), 'QTECH'
    elif host == 'shop.nag.ru' and path.startswith('/product/'):
        heading = soup.select_one('h1')
        for node in soup.find_all(string=lambda s: s and s.strip() in ('Артикул:', 'Артикул', 'Производитель:', 'Производитель')):
            parent = node.parent.parent
            value = parent.get_text(' ', strip=True).replace(node.strip(), '', 1).strip(' :')
            if len(value) < 150:
                if 'Артикул' in node:
                    mpn = value
                else:
                    brand = value
    if heading:
        name = heading.get_text(' ', strip=True)
        if brand in ('D-Link', 'QTECH'):
            mpn = name  # Model heading on a verified manufacturer's detail page.
        props = []
        table_selector = '.sub-content-block.table table tr' if host == 'dlink.ru' else '.table-block table tr' if host == 'www.qtech.ru' else 'table tr'
        for row in soup.select(table_selector):
            if row.select_one('select, input'):
                continue
            cells = row.find_all(['td', 'th'], recursive=False)
            if len(cells) == 2:
                label, value = [cell.get_text(' ', strip=True) for cell in cells]
                if label and value:
                    props.append({'name': label, 'value': value})
        description = soup.select_one('.sub-content-block.open') if host == 'dlink.ru' else soup.select_one('[itemprop="description"]')
        return {'name': name, 'brand': brand, 'mpn': mpn,
                'description': text(description), 'additionalProperty': props,
                'offers': {'price': text(soup.select_one('.product-card__request-price')),
                           'availability': text(soup.select_one('[itemprop="availability"]'))}}
    scopes = soup.select('[itemscope][itemtype$="/Product"]')
    if len(scopes) == 1:
        scope = scopes[0]
        return {field: text(scope.select_one(f'[itemprop="{field}"]'))
                for field in ('name', 'brand', 'mpn', 'description')}
    return {}


def listing(soup, url):
    host, path = urlsplit(url).hostname, urlsplit(url).path
    products, pages = [], []
    if (host == 'dlink.ru' and path.endswith('.html') or
            host == 'www.qtech.ru' and re.fullmatch(r'/catalog/switches/[^/]+/[^/]+/[^/]+/', path) or
            host == 'shop.nag.ru' and path.startswith('/product/')):
        return [], []
    if host == 'dlink.ru' and not path.endswith('.html'):
        products = [a['href'] for a in soup.select('.product-wrapper a[href]')
                    if re.fullmatch(r'/ru/products/\d+/\d+\.html', a['href'])]
    elif host == 'www.qtech.ru' and path.startswith('/catalog/switches/'):
        products = [a['href'] for a in soup.select('a.product-compare__image__inner[href]')]
        pages = [a['href'] for a in soup.select('h2.title-border a[href], h3.product-category__title a[href]') if a['href'].startswith(path) and a['href'] != path]
    elif host == 'shop.nag.ru' and path.startswith('/catalog/'):
        products = [a['href'] for a in soup.select('a[href^="/product/"]')]
    if not products:
        products = [a.get('href') for a in soup.select('[itemtype$="/Product"] a[itemprop="url"][href], a.product-card[href], .product-card a[href]')]
    pages += [a['href'] for a in soup.select('a[rel="next"][href], .pagination a[href], a.page-link[href]')]
    return products, pages
