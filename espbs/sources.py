"""Source registry and conservative manufacturer enrichment."""

import copy
from urllib.parse import urljoin, urlsplit

from . import eltex, olnisa
from .storage import utc_now
from .traffic import SourceBlocked

# Explicit aliases verified against official pages on 2026-10-15. Suffixes are
# significant: MES2428_DC is not MES2428. Never infer aliases from fuzzy names.
ALIASES = {
    'MES2424B': 'https://eltex.ru/product/kommutator_dostupa_mes2424b/',
    'MES2428': 'https://eltex.ru/product/kommutator_dostupa_mes2428/',
    'MES2428B': 'https://eltex.ru/product/kommutator_dostupa_mes2428b/',
    'MES2411X': 'https://eltex.ru/product/kommutator_dostupa_mes2411x/',
}
REGISTRY = {
    'eltex': {'id': 'eltex', 'name': 'Eltex — официальный каталог MES',
              'default_url': eltex.CATALOG, 'enrichments': ['none'],
              'description': 'Коммутаторы MES с официального сайта производителя.'},
    'olnisa': {'id': 'olnisa', 'name': 'Olnisa — разделы производителей',
               'default_url': olnisa.CATALOG, 'enrichments': ['eltex', 'none'],
               'description': 'Раздел производителя со всеми опубликованными страницами или отдельная карточка. Фото магазина не используются.'},
}


def configuration(source='eltex', start_url='', enrichment=None):
    if source not in REGISTRY:
        raise ValueError('Неизвестный источник')
    entry = REGISTRY[source]
    enrichment = enrichment if enrichment is not None else entry['enrichments'][0]
    if enrichment not in entry['enrichments']:
        raise ValueError('Обогащение не поддерживается для этого источника')
    url = start_url.strip() or entry['default_url']
    if source == 'olnisa':
        url = olnisa.safe_url(url)
        if url.endswith('/robots.txt'):
            raise ValueError('Укажите каталог или карточку товара')
    elif url != eltex.CATALOG:
        raise ValueError('Для Eltex пока поддерживается каталог коммутаторов MES')
    return {'source': source, 'start_url': url, 'enrichment': enrichment}


def official_images(record):
    raw = record.get('provenance', {}).get('product_jsonld', {}).get('image', [])
    raw = raw if isinstance(raw, list) else [raw]
    images = []
    for value in raw:
        if isinstance(value, dict):
            value = value.get('url', '')
        if not isinstance(value, str) or not value:
            continue
        url = urljoin(record['source_url'], value)
        p = urlsplit(url)
        if p.scheme == 'https' and p.netloc == 'eltex.ru' and url not in images:
            images.append(url)
    return images


def enrich(record, client):
    result = copy.deepcopy(record)
    result['enrichment'] = {'status': 'REVIEW', 'reason': 'Нет подтверждённого соответствия бренда и артикула'}
    mpn = record.get('mpn', '').strip().upper()
    url = ALIASES.get(mpn) if record.get('manufacturer', '').strip().casefold() == 'eltex' else None
    if url:
        try:
            official = eltex.product(client.get(url), url)
            # Check the reviewed alias still refers to the same official model.
            valid = (official['manufacturer'].casefold() == 'eltex'
                     and official['name'] == 'Коммутатор доступа ' + mpn
                     and (not official['mpn'] or official['mpn'].strip().upper() == mpn))
            if not valid:
                raise ValueError('Официальная карточка больше не подтверждает проверенный алиас')
            result['official'] = official
            result['images'] = official_images(official)
            for field in ('description', 'attributes', 'documents'):
                result[field] = official[field]
            result['provenance']['original_description'] = record['description']
            result['provenance']['official_fields'] = {
                field: {'source_url': url, 'collected_at': utc_now()}
                for field in ('description', 'attributes', 'documents', 'images')}
            result['enrichment'] = {'status': 'MATCHED', 'method': 'reviewed_alias',
                                     'mpn': mpn, 'source_url': url,
                                     'alias_verified_at': '2026-10-15'}
        except (eltex.Stopped, SourceBlocked):
            raise
        except Exception as error:
            result['enrichment'] = {'status': 'ERROR', 'reason': str(error), 'source_url': url}
    issues = list(result['quality']['issues'])
    if result['enrichment']['status'] != 'MATCHED':
        issues.append(result['enrichment']['reason'])
    elif not result['images']:
        issues.append('У производителя нет доступного изображения')
    result['quality'] = {'status': 'REVIEW' if issues else 'GOOD', 'issues': issues,
                         'attribute_count': len(result['attributes'])}
    return result
