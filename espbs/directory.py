"""Persistent user-maintained source rules and manufacturer directory."""
import copy
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from . import eltex, olnisa
from .sources import ALIASES, enrich as legacy_enrich
from .storage import canonical_json, utc_now
from .universal import Adapter, Client, public_url, rules, objects


def key(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError('Укажите бренд/артикул длиной до 200 символов')
    return value.strip().casefold()


class Directory:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'directory.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS profiles (host TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS manufacturers (brand TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mappings (brand TEXT, mpn TEXT, url TEXT, PRIMARY KEY(brand,mpn));
                CREATE TABLE IF NOT EXISTS official_cache (identity TEXT PRIMARY KEY, time TEXT, value TEXT);
            ''')
            seed = {'brand': 'Eltex', 'home_url': 'https://eltex.ru/', 'template': '', 'selectors': {}}
            db.execute('INSERT OR IGNORE INTO manufacturers VALUES (?,?)', ('eltex', canonical_json(seed)))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def profile(self, url):
        host = urlsplit(public_url(url)).hostname
        with self.db() as db:
            row = db.execute('SELECT value FROM profiles WHERE host=?', (host,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_profile(self, url, selectors):
        host = urlsplit(public_url(url)).hostname
        selectors = rules(selectors)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)', (host, canonical_json(selectors)))
        return {'host': host, 'selectors': selectors}

    def manufacturers(self):
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT value FROM manufacturers ORDER BY brand')]

    def manufacturer(self, brand):
        with self.db() as db:
            row = db.execute('SELECT value FROM manufacturers WHERE brand=?', (key(brand),)).fetchone()
        return json.loads(row[0]) if row else None

    def save_manufacturer(self, value):
        brand = key(value.get('brand'))
        home = public_url(value.get('home_url'))
        if urlsplit(home).hostname == 'olnisa.ru' or urlsplit(home).hostname.endswith('.olnisa.ru'):
            raise ValueError('Olnisa — магазин, не официальный источник изображений')
        template = value.get('template', '').strip()
        if template:
            if template.count('{mpn}') != 1 or '{' in template.replace('{mpn}', '') or '}' in template.replace('{mpn}', ''):
                raise ValueError('Шаблон должен содержать ровно один {mpn}')
            if urlsplit(public_url(template.replace('{mpn}', 'TEST'))).netloc != urlsplit(home).netloc:
                raise ValueError('Шаблон должен вести на указанный официальный сайт')
        result = {'brand': value['brand'].strip(), 'home_url': home, 'template': template,
                  'selectors': rules(value.get('selectors', {}))}
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO manufacturers VALUES (?,?)', (brand, canonical_json(result)))
        return result

    def save_mapping(self, value):
        brand, mpn = key(value.get('brand')), key(value.get('mpn'))
        manufacturer = self.manufacturer(brand)
        if not manufacturer:
            raise ValueError('Сначала добавьте производителя')
        url = public_url(value.get('url'))
        if urlsplit(url).netloc != urlsplit(manufacturer['home_url']).netloc:
            raise ValueError('Карточка должна находиться на официальном сайте производителя')
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO mappings VALUES (?,?,?)', (brand, mpn, url))
        return {'brand': brand, 'mpn': mpn, 'url': url}

    def mappings(self, limit=100):
        with self.db() as db:
            return [{'brand': r[0], 'mpn': r[1], 'url': r[2]} for r in db.execute(
                'SELECT brand,mpn,url FROM mappings ORDER BY brand,mpn LIMIT ?', (limit,))]

    def resolve(self, brand, mpn):
        manufacturer = self.manufacturer(brand)
        if not manufacturer:
            return None, None
        with self.db() as db:
            row = db.execute('SELECT url FROM mappings WHERE brand=? AND mpn=?', (key(brand), key(mpn))).fetchone()
        url = row[0] if row else None
        if url and urlsplit(url).netloc != urlsplit(manufacturer['home_url']).netloc:
            url = None
        if not url and manufacturer['template']:
            url = manufacturer['template'].replace('{mpn}', quote(mpn.strip(), safe=''))
        return manufacturer, url

    def cached(self, identity):
        with self.db() as db:
            row = db.execute('SELECT time,value FROM official_cache WHERE identity=?', (identity,)).fetchone()
        if row and (datetime.now(timezone.utc) - datetime.fromisoformat(row[0])).total_seconds() < 86400:
            return json.loads(row[1])
        return None

    def cache(self, identity, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO official_cache VALUES (?,?,?)', (identity, utc_now(), canonical_json(value)))


def detect(root, url, selectors=None):
    url = public_url(url)
    profile = Directory(root).profile(url) if selectors is None else rules(selectors)
    host = urlsplit(url).hostname
    if not profile and host == 'olnisa.ru':
        try:
            olnisa.safe_url(url)
        except ValueError:
            pass
        else:
            return {'source': 'olnisa', 'start_url': url, 'enrichment': 'none'}
    if not profile and url == eltex.CATALOG:
        return {'source': 'eltex', 'start_url': url, 'enrichment': 'none'}
    return {'source': 'generic', 'start_url': url, 'enrichment': 'none', 'selectors': profile}


def probe(root, url, selectors=None):
    config = detect(root, url, selectors)
    adapter = {'olnisa': olnisa, 'eltex': eltex}.get(config['source']) or Adapter(config.get('selectors'))
    client = Client(config['start_url'])
    html = client.get(config['start_url'])
    links, pages = adapter.listing(html, config['start_url'])
    samples, errors = [], []
    for link in links[:3]:
        try:
            record = adapter.product(html if link == config['start_url'] else client.get(link), link)
            samples.append(record)
        except eltex.Stopped:
            raise
        except Exception as error:
            errors.append({'url': link, 'error': str(error)})
    return {'config': config, 'samples': samples, 'errors': errors, 'discovered': len(links),
            'pages': len(pages), 'can_start': bool(samples)}


class Enricher:
    def __init__(self, root, stopped=lambda: False):
        self.directory = Directory(root)
        self.stopped = stopped
        self.clients = {}

    def client(self, url):
        origin = urlsplit(url).netloc
        if origin not in self.clients:
            self.clients[origin] = Client(url, self.stopped)
        return self.clients[origin]

    def close(self):
        for client in self.clients.values():
            client.close()

    def enrich(self, record):
        # A re-enrichment starts from the original source snapshot, not previously
        # merged fields. This also avoids preserving stale successful images.
        original = copy.deepcopy(record.get('original_record', record))
        original.pop('original_record', None)
        result = copy.deepcopy(original)
        result['original_record'] = original
        result['images'] = []
        brand, mpn = original.get('manufacturer','').strip(), original.get('mpn','').strip()
        def fail(status, reason):
            result['enrichment'] = {'status': status, 'reason': reason}
            result['quality'] = {'status': 'REVIEW', 'issues': [reason],
                                 'attribute_count': len(result.get('attributes',{}))}
            return result
        if not brand or not mpn:
            return fail('MISSING_IDENTITY', 'Для сопоставления нужны бренд и точный MPN')
        manufacturer, url = self.directory.resolve(brand, mpn)
        if not manufacturer:
            return fail('NO_MANUFACTURER', 'Добавьте официальный сайт бренда ' + brand)
        if not url and key(brand) == 'eltex' and mpn.upper() in ALIASES and urlsplit(manufacturer['home_url']).netloc == 'eltex.ru':
            url = ALIASES[mpn.upper()]
            method = 'reviewed_alias'
        else:
            method = 'exact_brand_mpn'
        if not url:
            return fail('NEEDS_MAPPING', 'Добавьте URL официальной карточки для ' + brand + ' ' + mpn)
        # One cache entry per identity; configuration changes invalidate it.
        identity = canonical_json([key(brand), key(mpn)])
        revision = hashlib.sha256(canonical_json([manufacturer, url, method]).encode()).hexdigest()
        cached = self.directory.cached(identity)
        try:
            if cached and cached.get('revision') == revision:
                official = cached['product']
            elif method == 'reviewed_alias':
                merged = legacy_enrich(original, self.client(url))
                if merged['enrichment']['status'] != 'MATCHED':
                    return fail('ERROR', merged['enrichment']['reason'])
                official = merged['official']
                official['images'] = merged['images']
            else:
                html = self.client(url).get(url)
                official = Adapter(manufacturer.get('selectors')).product(html, url)
                if key(official.get('manufacturer','')) != key(brand) or key(official.get('mpn','')) != key(mpn):
                    return fail('MISMATCH', 'Бренд или MPN официальной карточки не совпадает')
                raw = objects(BeautifulSoup(html, 'html.parser'))
                images = raw[0].get('image', []) if len(raw) == 1 else []
                if not isinstance(images, list):
                    images = [images]
                official['images'] = []
                for image in images:
                    if isinstance(image, dict):
                        image = image.get('url','')
                    if not isinstance(image, str) or not image:
                        continue
                    candidate = public_url(urljoin(url, image))
                    if urlsplit(candidate).netloc == urlsplit(url).netloc and candidate not in official['images']:
                        official['images'].append(candidate)
            if not cached or cached.get('revision') != revision:
                official.setdefault('provenance', {}).setdefault('collected_at', utc_now())
                self.directory.cache(identity, {'revision': revision, 'product': official})
            result['official'] = official
            for field in ('description', 'attributes', 'documents', 'images'):
                result[field] = official.get(field, [] if field in ('documents','images') else {} if field == 'attributes' else '')
            result.setdefault('provenance', {})['official_fields'] = {
                field: {'source_url': url, 'collected_at': official.get('provenance',{}).get('collected_at', utc_now())}
                for field in ('description','attributes','documents','images')}
            result['enrichment'] = {'status': 'MATCHED', 'method': method, 'source_url': url,
                                     'cached': bool(cached and cached.get('revision') == revision)}
            result['quality'] = {'status': 'GOOD', 'issues': [], 'attribute_count': len(result['attributes'])}
            return result
        except eltex.Stopped:
            raise
        except Exception as error:
            return fail('ERROR', str(error))
