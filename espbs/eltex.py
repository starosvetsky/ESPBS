"""Bounded, polite collection of the public Eltex Ethernet catalogue."""

import hashlib
import json
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

CATALOG = 'https://eltex.ru/catalog/ethernet-kommutatory-mes/'
AGENT = 'ESPBS/0.2 (+https://github.com/starosvetsky/ESPBS)'


def safe_url(value, base=CATALOG):
    url = urljoin(base, value)
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != 'eltex.ru' or parts.fragment:
        raise ValueError('Unexpected source URL: ' + url)
    return url


def listing(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    products = list(dict.fromkeys(safe_url(a['href'], url)
                    for a in soup.select('.good a[href^="/product/"]')))
    if not products:
        raise ValueError('Catalogue contains no product links; source layout may have changed')
    pages = []
    for a in soup.select('a[href]'):
        href = urljoin(url, a['href'])
        if re.fullmatch(re.escape(CATALOG) + r'\?page=\d+', href):
            pages.append(href)
    return products, sorted(set(pages), key=lambda x: int(x.split('=')[-1]))


def product(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    objects = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                objects.extend(item.get('@graph', [item]))
    raw = next((x for x in objects if x.get('@type') == 'Product'), None)
    if not raw or not raw.get('name'):
        raise ValueError('Product structured data missing')
    attributes = {}
    for prop in raw.get('additionalProperty', []):
        if prop.get('name') and 'value' in prop:
            attributes.setdefault(prop['name'], []).append(prop['value'])
    breadcrumbs = next((x for x in objects if x.get('@type') == 'BreadcrumbList'), {})
    documents = []
    for a in soup.select('a[href]'):
        href = urljoin(url, a['href'])
        if href.startswith('https://eltex.ru/storage/upload_center/files/'):
            entry = {'url': safe_url(href), 'name': a.get_text(' ', strip=True)}
            if entry not in documents:
                documents.append(entry)
    heading = soup.h1.get_text(' ', strip=True) if soup.h1 else ''
    issues = []
    if not raw.get('mpn'):
        issues.append('No explicit manufacturer part number; automatic merging disabled')
    if not attributes:
        issues.append('No structured specifications')
    return {'source': 'eltex', 'external_id': urlsplit(url).path,
            'source_url': safe_url(url), 'name': raw['name'],
            'manufacturer': raw.get('brand', {}).get('name', ''),
            'mpn': raw.get('mpn', ''), 'description': raw.get('description', ''),
            'attributes': attributes, 'documents': documents,
            'quality': {'status': 'REVIEW' if issues else 'GOOD', 'issues': issues,
                        'attribute_count': len(attributes)},
            'provenance': {'heading': heading, 'product_jsonld': raw,
                           'breadcrumbs_jsonld': breadcrumbs,
                           'html_sha256': hashlib.sha256(html.encode()).hexdigest()},
            'attachments_downloaded': False}


class Stopped(Exception):
    pass


class Client:
    def __init__(self, stopped=lambda: False):
        self.stopped = stopped
        self.session = requests.Session()
        self.session.headers['User-Agent'] = AGENT
        self.last_request = 0
        self.rules = None

    def close(self):
        self.session.close()

    def get(self, url):
        url = safe_url(url)
        if self.rules is None and not url.endswith('/robots.txt'):
            text = self.get('https://eltex.ru/robots.txt')
            # urllib handles ordinary rules. Supplement wildcard rules, which
            # urllib does not implement, conservatively for this bounded source.
            self.rules = RobotFileParser()
            self.rules.parse(text.splitlines())
            self.wildcards = [line.split(':', 1)[1].strip() for line in text.splitlines()
                              if line.lower().startswith('disallow:') and '*' in line]
        if self.rules is not None:
            path = urlsplit(url).path + ('?' + urlsplit(url).query if urlsplit(url).query else '')
            if not self.rules.can_fetch(AGENT, url) or any(
                re.match(re.escape(rule).replace(r'\*', '.*').replace(r'\$', '$'), path)
                for rule in self.wildcards):
                raise ValueError('robots.txt disallows ' + url)
        while time.monotonic() - self.last_request < 2:
            if self.stopped():
                raise Stopped()
            time.sleep(0.1)
        if self.stopped():
            raise Stopped()
        self.last_request = time.monotonic()
        with self.session.get(url, timeout=(5, 20), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                # Refuse redirects rather than silently leaving the checked URL.
                raise ValueError('Source redirected; inspect before resuming: ' + response.headers.get('Location', ''))
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                if self.stopped():
                    raise Stopped()
                size += len(chunk)
                if size > 6 * 1024 * 1024:
                    raise ValueError('Source response exceeds 6 MiB')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8')
