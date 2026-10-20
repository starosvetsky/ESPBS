"""Bounded public HTTPS reader and structured-data/CSS source adapter."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from .robots import Robots

from bs4 import BeautifulSoup
import soupsieve

from .eltex import AGENT, Stopped
from .storage import utc_now


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Укажите публичную HTTPS-ссылку')
    p = urlsplit(value.strip())
    if (p.scheme != 'https' or not p.hostname or p.username or p.password
            or p.port not in (None, 443) or any(ord(c) < 33 for c in value)):
        raise ValueError('Нужна HTTPS-ссылка без логина и нестандартного порта')
    host = p.hostname.encode('idna').decode('ascii').lower()
    if '.' not in host or host.endswith(('.localhost', '.local', '.internal')):
        raise ValueError('Локальные адреса недоступны')
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError('Локальные адреса недоступны')
    except ValueError as error:
        if 'Локальные' in str(error):
            raise
    return urlunsplit(('https', host, p.path or '/', p.query, ''))


def public_addresses(host):
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise ValueError('Источник разрешается в непубличный IP-адрес')
    return addresses


def normalize_input(value):
    url = public_url(value.strip())
    p = urlsplit(url)
    if 'https:' in p.path or 'http:' in p.path:
        raise ValueError('В поле вставлены две ссылки подряд. Укажите один адрес страницы.')
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith('utm_') and k.lower() not in ('ysclid', 'yclid', 'gclid', 'fbclid', 'etext')])
    path = p.path
    if p.hostname == 'olnisa.ru' and path.startswith('/manufacturers/') and not path.endswith('/'):
        path += '/'
    return urlunsplit((p.scheme, p.netloc, path, query, ''))


class Redirect(Exception):
    def __init__(self, url):
        self.url = url


class Client:
    def __init__(self, url, stopped=lambda: False, root='data', redirect_origins=()):
        from .traffic import Traffic
        self.traffic = Traffic(root)
        self.origin = 'https://' + urlsplit(public_url(url)).netloc
        self.root = root
        self.redirect_origins = set(redirect_origins) | {self.origin}
        self.stopped = stopped
        self.rules = None
        self.last_request = 0
        self.delay = 2

    def close(self):
        pass

    def get(self, url, _redirects=0, *, sink=None, max_bytes=6 * 1024 * 1024):
        url = public_url(url)
        p = urlsplit(url)
        if 'https://' + p.netloc != self.origin:
            raise ValueError('Ссылка выходит за пределы выбранного сайта')
        if self.rules is None:
            text = self._request(self.origin + '/robots.txt', robots=True)
            self.rules = Robots()
            self.rules.parse(text.splitlines())
            self.delay = max(2, self.rules.crawl_delay(AGENT) or self.rules.crawl_delay('*') or 0)
        path = p.path + ('?' + p.query if p.query else '')
        if not self.rules.can_fetch(AGENT, url):
            raise ValueError('robots.txt запрещает ' + url)
        try:
            result = self._request(url) if sink is None else self._request(url, sink=sink, max_bytes=max_bytes)
            self.last_url = url
            return result
        except Redirect as redirect:
            if _redirects >= 5:
                raise ValueError('Слишком много перенаправлений: ' + url)
            target_origin = 'https://' + urlsplit(redirect.url).netloc
            if target_origin != self.origin:
                if target_origin not in self.redirect_origins:
                    raise ValueError('Непроверенный домен перенаправления')
                # Independent robots policy on each explicitly permitted origin.
                child = Client(redirect.url, self.stopped, self.root, self.redirect_origins)
                try:
                    result = child.get(redirect.url, _redirects + 1, sink=sink, max_bytes=max_bytes)
                    self.last_url = child.last_url
                    return result
                finally:
                    child.close()
            return self.get(redirect.url, _redirects + 1, sink=sink, max_bytes=max_bytes)

    def _request(self, url, robots=False, **kwargs):
        with self.traffic.request(url, self.delay, self.stopped):
            return self._request_locked(url, robots, **kwargs)

    def _request_locked(self, url, robots=False, *, sink=None, max_bytes=6 * 1024 * 1024):
        while time.monotonic() - self.last_request < self.delay:
            if self.stopped():
                raise Stopped()
            time.sleep(.1)
        if self.stopped():
            raise Stopped()
        p = urlsplit(url)
        addresses = public_addresses(p.hostname)
        conn = http.client.HTTPSConnection(p.hostname, timeout=20)
        # Pin the validated IP for the connection; TLS still verifies the original
        # hostname. A second DNS lookup cannot rebind to a private address.
        conn._create_connection = lambda address, timeout, source_address=None: socket.create_connection(
            (addresses[0], 443), timeout, source_address)
        self.last_request = time.monotonic()
        try:
            conn.request('GET', p.path + ('?' + p.query if p.query else ''),
                         headers={'User-Agent': AGENT, 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            self.traffic.response(url, response.status, response.getheader('Retry-After'))
            if robots and response.status == 404:
                return ''
            if not robots and response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if isinstance(location, str) and location:
                    target = public_url(urljoin(url, location))
                    if 'https://' + urlsplit(target).netloc not in self.redirect_origins:
                        raise ValueError('Перенаправление на другой сайт требует проверки: ' + target)
                    raise Redirect(target)
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}: {url}; редиректы и ограничения не обходятся')
            length = response.getheader('Content-Length')
            if length is not None and int(length) > max_bytes:
                raise ValueError('Ответ превышает лимит размера')
            chunks, size = [], 0
            while True:
                if self.stopped():
                    raise Stopped()
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('Ответ превышает лимит размера')
                if sink is None:
                    chunks.append(chunk)
                else:
                    sink(chunk)
            if length is not None and size != int(length):
                raise ValueError('Ответ оборван: размер не совпадает с Content-Length')
            if sink is not None:
                return {'bytes': size, 'content_type': response.getheader('Content-Type', '')}
            return b''.join(chunks).decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
        finally:
            conn.close()


FIELDS = {'name', 'manufacturer', 'mpn', 'description', 'price', 'availability', 'product_links', 'next_links'}


def rules(value):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError('Неизвестные поля правил CSS')
    for selector in value.values():
        if not isinstance(selector, str) or len(selector) > 500:
            raise ValueError('Некорректный CSS-селектор')
        if selector:
            try:
                soupsieve.compile(selector)
            except soupsieve.SelectorSyntaxError as error:
                raise ValueError('Некорректный CSS-селектор: ' + str(error)) from error
    return value


def objects(soup):
    found = []
    def walk(value, depth=0):
        if depth > 20:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
        elif isinstance(value, dict):
            kind = value.get('@type', [])
            kinds = kind if isinstance(kind, list) else [kind]
            if any(isinstance(k, str) and k.rsplit('/', 1)[-1] == 'Product' for k in kinds):
                found.append(value)
            for key in ('@graph', 'itemListElement', 'item', 'mainEntity'):
                if key in value:
                    walk(value[key], depth + 1)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.get_text()))
        except (ValueError, TypeError, RecursionError):
            continue
    return found


class Adapter:
    def __init__(self, selectors=None):
        self.selectors = rules(selectors or {})

    def product(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        candidates = objects(soup)
        # Multiple products are a listing, never silently select a related item.
        raw = candidates[0] if len(candidates) == 1 else {}
        declared_url = raw.get('url')
        if isinstance(declared_url, str) and declared_url:
            declared = urlsplit(urljoin(url, declared_url))
            current = urlsplit(url)
            if (declared.netloc, declared.path.rstrip('/')) != (current.netloc, current.path.rstrip('/')):
                raise ValueError('Разметка Product относится к другой странице; текущий адрес не подтверждён как карточка')
        if not candidates:
            from .html_sources import product as html_product
            from .recognition import html_product as inferred_product, micro_product, clean
            raw = micro_product(clean(soup)) or html_product(soup, url) or inferred_product(soup, url)
        def field(key, fallback=''):
            selector = self.selectors.get(key)
            node = soup.select_one(selector) if selector else None
            return (node.get('content') or node.get_text(' ', strip=True)) if node else fallback
        brand = raw.get('brand', raw.get('manufacturer', ''))
        if isinstance(brand, dict):
            brand = brand.get('name', '')
        name = field('name', raw.get('name', ''))
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Карточка не распознана: нужны структурированные данные товара или название вместе с артикулом и характеристиками. Один заголовок раздела не считается товаром; доступны правила CSS.')
        attributes = {}
        for prop in raw.get('additionalProperty', []):
            if isinstance(prop, dict) and prop.get('name') and 'value' in prop:
                attributes.setdefault(str(prop['name']), []).append(prop['value'])
        offers = raw.get('offers', {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if not isinstance(offers, dict):
            offers = {}
        brand, mpn = str(field('manufacturer', brand) or ''), str(field('mpn', raw.get('mpn','')) or '')
        issues = [label for value, label in [(brand, 'Нет бренда'), (mpn, 'Нет точного MPN')] if not value]
        if raw.get('_recognition') == 'html-evidence':
            issues.append('Поля определены по структуре HTML; требуется проверка')
        from .materials import documents, scope
        from .recognition import pairs
        if not attributes:
            for label, val in pairs(scope(html)):
                attributes.setdefault(label, []).append(val)
        # Store-side images are deliberately excluded, including nested JSON-LD.
        return {'source': urlsplit(url).hostname, 'source_url': public_url(url), 'external_id': public_url(url),
                'name': name, 'manufacturer': brand, 'mpn': mpn,
                'sku': str(raw.get('sku') or ''),
                'description': str(field('description', raw.get('description','')) or ''),
                'attributes': attributes, 'documents': documents(html, url), 'images': [],
                'offer': {'price_text': str(field('price', offers.get('price',''))),
                          'currency': str(offers.get('priceCurrency','')),
                          'availability': str(field('availability', offers.get('availability',''))),
                          'source_url': url, 'collected_at': utc_now()},
                'quality': {'status': 'REVIEW' if issues else 'GOOD', 'issues': issues,
                            'attribute_count': len(attributes)},
                'provenance': {'collected_at': utc_now(), 'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
                               'parser': 'jsonld-css-v2', 'recognition': raw.get('_recognition', 'jsonld' if candidates else 'adapter-or-css'), 'selectors': self.selectors},
                'attachments_downloaded': False}

    def listing(self, html, url):
        soup = BeautifulSoup(html, 'html.parser')
        origin = urlsplit(url).netloc
        def valid(values):
            result = []
            for value in values:
                try:
                    link = public_url(urljoin(url, value))
                    if urlsplit(link).netloc == origin and link not in result:
                        result.append(link)
                except (ValueError, TypeError):
                    continue
                if len(result) >= 10_000:
                    break
            return result
        links = []
        selector = self.selectors.get('product_links')
        if selector:
            links = valid(a.get('href','') for a in soup.select(selector) if a.get('href'))
        from .html_sources import listing as html_listing
        html_links, html_pages = html_listing(soup, url)
        from .recognition import discover, html_product as inferred_product, itemlist_links, pagination, clean
        candidates = objects(soup)
        declared = candidates[0].get('url') if len(candidates) == 1 else None
        declared_links = valid([declared]) if isinstance(declared, str) and declared else []
        foreign_card = bool(declared_links and urlsplit(declared_links[0]).path.rstrip('/') != urlsplit(url).path.rstrip('/'))
        # A primary structured card takes precedence over related-product links.
        if not selector and not foreign_card and not itemlist_links(soup, url) and (len(candidates) == 1 or inferred_product(soup, url)):
            self.product(html, url)
            return [url], []
        if not links:
            links = valid(html_links)
        if links:
            html_pages = list(dict.fromkeys(html_pages + pagination(clean(soup), url)))
        if not links and not html_pages:
            discovered, extra_pages = discover(soup, url)
            links = valid(discovered) or (declared_links if foreign_card else [])
            html_pages = extra_pages if links else []
        if not links and not html_pages:
            candidates = objects(soup)
            if len(candidates) > 1:
                links = valid(x.get('url') for x in candidates if x.get('url'))
            else:
                try:
                    self.product(html, url)
                except ValueError as error:
                    raise ValueError('Структура страницы пока не распознана: не найдены надёжные ссылки на товары или признаки отдельной карточки. Возможно, данные загружаются JavaScript; нужны правила CSS или адаптер.') from error
                links = [url]
        if not links and not html_pages:
            raise ValueError('Каталог не распознан: для структуры этого сайта требуется адаптер')
        selector = self.selectors.get('next_links')
        pages = valid(a.get('href','') for a in soup.select(selector) if a.get('href')) if selector else valid(html_pages)
        return links, pages
