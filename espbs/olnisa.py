"""Olnisa Eltex section. Never extract or download Olnisa images."""

import hashlib
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .eltex import Client as BaseClient
from .storage import utc_now

CATALOG = 'https://olnisa.ru/manufacturers/eltex/'


def advertised_count(html):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('h1 span')
    match = re.search(r'\(([\d\s\u00a0]+)', heading.get_text()) if heading else None
    return int(re.sub(r'\s', '', match[1])) if match else None


def safe_url(value, base=CATALOG):
    url = urljoin(base, value)
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'olnisa.ru' or p.fragment or p.query
            or not (p.path == '/robots.txt' or re.fullmatch(r'/manufacturers/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*/', p.path))):
        raise ValueError('Укажите раздел производителя Olnisa /manufacturers/бренд/ или его карточку')
    return url


def listing(html, url):
    url = safe_url(url)
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('.catalog-detail-mini-params h1'):
        return [safe_url(url)], []
    urls = []
    section = 'https://olnisa.ru/' + '/'.join(urlsplit(url).path.strip('/').split('/')[:2]) + '/'
    # Pagination belongs to the selected category, not the entire manufacturer.
    # The same base must be recovered when parsing page 2 and later pages.
    category = re.sub(r'/page-[1-9]\d*/$', '/', url)
    for a in soup.select('a.catalog-item[href]'):
        candidate = urljoin(url, a['href'])
        if candidate.startswith(section) and candidate != section:
            try:
                urls.append(safe_url(candidate))
            except ValueError:
                # A tracking/query link must not abort otherwise valid results.
                continue
    if not urls:
        raise ValueError('Карточки Olnisa не найдены; проверьте структуру страницы')
    # Follow published path pagination, not robots-disallowed query variants.
    pages = []
    for a in soup.select('a.page_link[href], .catalog-show-all[data-url]'):
        candidate = urljoin(url, a.get('href') or a.get('data-url'))
        if re.fullmatch(re.escape(category) + r'page-[1-9]\d*/', candidate):
            pages.append(safe_url(candidate))
    return list(dict.fromkeys(urls)), list(dict.fromkeys(pages))


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
