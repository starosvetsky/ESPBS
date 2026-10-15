"""Bounded public HTTPS reader and structured-data/CSS source adapter."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

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


class Client:
    def __init__(self, url, stopped=lambda: False):
        self.origin = 'https://' + urlsplit(public_url(url)).netloc
        self.stopped = stopped
        self.rules = None
        self.last_request = 0
        self.delay = 2

    def close(self):
        pass

    def get(self, url):
        url = public_url(url)
        p = urlsplit(url)
        if 'https://' + p.netloc != self.origin:
            raise ValueError('Ссылка выходит за пределы выбранного сайта')
        if self.rules is None:
            text = self._request(self.origin + '/robots.txt', robots=True)
            self.rules = RobotFileParser()
            self.rules.parse(text.splitlines())
            self.wildcards = [line.split(':',1)[1].split('#')[0].strip() for line in text.splitlines()
                              if line.lower().startswith('disallow:') and '*' in line]
            self.delay = max(2, self.rules.crawl_delay(AGENT) or self.rules.crawl_delay('*') or 0)
        path = p.path + ('?' + p.query if p.query else '')
        if not self.rules.can_fetch(AGENT, url) or any(
                re.match(re.escape(rule).replace(r'\*', '.*').replace(r'\$', '$'), path)
                for rule in self.wildcards):
            raise ValueError('robots.txt запрещает ' + url)
        return self._request(url)

    def _request(self, url, robots=False):
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
            if robots and response.status == 404:
                return ''
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}: {url}; редиректы и ограничения не обходятся')
            chunks, size = [], 0
            while True:
                if self.stopped():
                    raise Stopped()
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > 6 * 1024 * 1024:
                    raise ValueError('Страница превышает 6 MiB')
                chunks.append(chunk)
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
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            kind = value.get('@type', [])
            if kind == 'Product' or isinstance(kind, list) and 'Product' in kind:
                found.append(value)
            for key in ('@graph', 'itemListElement', 'item'):
                if key in value:
                    walk(value[key])
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.get_text()))
        except (ValueError, TypeError):
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
        def field(key, fallback=''):
            selector = self.selectors.get(key)
            node = soup.select_one(selector) if selector else None
            return (node.get('content') or node.get_text(' ', strip=True)) if node else fallback
        brand = raw.get('brand', raw.get('manufacturer', ''))
        if isinstance(brand, dict):
            brand = brand.get('name', '')
        name = field('name', raw.get('name', ''))
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Товар не распознан: нет однозначного Product JSON-LD или правил поля name')
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
        # Store-side images are deliberately excluded, including nested JSON-LD.
        return {'source': urlsplit(url).hostname, 'source_url': public_url(url), 'external_id': public_url(url),
                'name': name, 'manufacturer': brand, 'mpn': mpn,
                'description': str(field('description', raw.get('description','')) or ''),
                'attributes': attributes, 'documents': [], 'images': [],
                'offer': {'price_text': str(field('price', offers.get('price',''))),
                          'currency': str(offers.get('priceCurrency','')),
                          'availability': str(field('availability', offers.get('availability',''))),
                          'source_url': url, 'collected_at': utc_now()},
                'quality': {'status': 'REVIEW' if issues else 'GOOD', 'issues': issues,
                            'attribute_count': len(attributes)},
                'provenance': {'collected_at': utc_now(), 'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
                               'parser': 'jsonld-css-v1', 'selectors': self.selectors},
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
        if not links:
            candidates = objects(soup)
            if len(candidates) > 1:
                links = valid(x.get('url') for x in candidates if x.get('url'))
            else:
                self.product(html, url)
                links = [url]
        if not links:
            raise ValueError('Нет ссылок на товары: задайте product_links в правилах сайта')
        selector = self.selectors.get('next_links')
        pages = valid(a.get('href','') for a in soup.select(selector) if a.get('href')) if selector else []
        return links, pages
