"""Olnisa Eltex section. Never extract or download Olnisa images."""

import hashlib
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .eltex import Client as BaseClient
from .storage import utc_now

CATALOG = 'https://olnisa.ru/manufacturers/eltex/'


def safe_url(value, base=CATALOG):
    url = urljoin(base, value)
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'olnisa.ru' or p.fragment or p.query
            or not (p.path == '/robots.txt' or re.fullmatch(r'/manufacturers/eltex/(?:[a-z0-9_-]+/)?', p.path))):
        raise ValueError('Поддерживается раздел https://olnisa.ru/manufacturers/eltex/ и его карточки')
    return url


def listing(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('.catalog-detail-mini-params h1'):
        return [safe_url(url)], []
    urls = []
    for a in soup.select('a.catalog-item[href]'):
        candidate = urljoin(url, a['href'])
        if candidate.startswith(CATALOG) and candidate != CATALOG:
            urls.append(safe_url(candidate))
    if not urls:
        raise ValueError('Карточки Olnisa не найдены; проверьте структуру страницы')
    # Query pagination is prohibited by this source's robots.txt.
    return list(dict.fromkeys(urls)), []


def product(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    panel = soup.select_one('.catalog-detail-mini-params')
    if not panel or not panel.h1:
        raise ValueError('Карточка Olnisa не распознана')
    fields = {}
    for title in panel.select('.catalog-detail-mini-params-grid .title'):
        value = title.find_next_sibling('span')
        if value:
            fields[title.get_text(' ', strip=True)] = value.get_text(' ', strip=True)
    brand = fields.get('Производитель', '')
    mpn = fields.get('Артикул', '')
    price = soup.select_one('.catalog-detail-price-block .normal-price')
    price_text = price.get_text(' ', strip=True) if price else ''
    description = soup.select_one('[itemprop="description"]')
    issues = [] if brand and mpn else ['Не указан бренд или артикул магазина']
    return {'source': 'olnisa', 'external_id': urlsplit(url).path,
            'source_url': safe_url(url), 'name': panel.h1.get_text(' ', strip=True),
            'manufacturer': brand, 'mpn': mpn,
            'description': description.get_text(' ', strip=True) if description else '',
            'offer': {'price_text': price_text, 'availability': fields.get('Наличие', ''),
                      'source_url': url, 'collected_at': utc_now()},
            'attributes': {}, 'documents': [], 'images': [],
            'quality': {'status': 'REVIEW', 'issues': issues, 'attribute_count': 0},
            'provenance': {'fields': fields, 'price_text': price_text,
                           'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
                           'collected_at': utc_now()},
            'attachments_downloaded': False}


class Client(BaseClient):
    validate_url = staticmethod(safe_url)
    robots_url = 'https://olnisa.ru/robots.txt'
