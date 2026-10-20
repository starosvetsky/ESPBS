"""Photo selection shared by collection, enrichment and export payloads."""
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .universal import objects, public_url

OFFICIAL_HOSTS = {'eltex.ru': 'Eltex', 'dlink.ru': 'D-Link', 'www.qtech.ru': 'QTECH', 'ostec.ru': 'OSTEC'}
IMAGE_HOSTS = {'shop.nag.ru': {'cdn.nag.shop'}}


def forbidden(url):
    host = (urlsplit(url).hostname or '').lower()
    return host == 'olnisa.ru' or host.endswith('.olnisa.ru')


def clean(values, base):
    if forbidden(base):
        return []
    if not isinstance(values, list):
        values = [values]
    result = []
    for value in values:
        if isinstance(value, dict):
            value = value.get('url') or value.get('contentUrl')
        if not isinstance(value, str) or not value:
            continue
        if 'no_photo' in value or 'no-photo' in value:
            continue
        try:
            url = public_url(urljoin(base, value))
        except ValueError:
            continue
        allowed = {urlsplit(base).netloc} | IMAGE_HOSTS.get(urlsplit(base).netloc, set())
        if not forbidden(url) and urlsplit(url).netloc in allowed and url not in result:
            result.append(url)
    return result


def extract(html, url):
    if forbidden(url):
        return []
    soup = BeautifulSoup(html, 'html.parser')
    raw = objects(soup)
    values = raw[0].get('image', []) if len(raw) == 1 else []
    if not values:
        values = [n.get('content') or n.get('src') or n.get('href') for n in
                  soup.select('[itemprop="image"], meta[property="og:image"]')]
    if not any(values):
        from .materials import image_candidates
        heading = soup.select_one('h1')
        values = image_candidates(html, heading.get_text(' ', strip=True) if heading else '')
    if urlsplit(url).hostname == 'dlink.ru':
        values = [n.get('src') for n in soup.select('img[src*="/up/prod/"]')]
    if urlsplit(url).hostname == 'shop.nag.ru':
        values = [n.get('src') for n in soup.select('img[class*="ImagesCarousel_itemImage"]')]
    return clean(values, url)


def select(record, policy, original=None):
    original = original or record.get('original_record', record)
    source = original.get('source_url', '')
    source_images = clean(original.get('images', []), source)
    if record.get('enrichment', {}).get('status') == 'SOURCE_OFFICIAL':
        source_images = clean(record.get('images', []), source)
    official_url = record.get('enrichment', {}).get('source_url', '')
    official = clean(record.get('images', []), official_url) if record.get('enrichment', {}).get('status') == 'MATCHED' else []
    if urlsplit(source).hostname in OFFICIAL_HOSTS or record.get('provenance', {}).get('official_source') == source:
        official, official_url = source_images, source
    if policy == 'store' or policy == 'fallback' and source_images:
        record['images'], chosen = source_images, source
    elif policy == 'none':
        record['images'], chosen = [], ''
    else:
        record['images'], chosen = official, official_url
    record.setdefault('provenance', {})['images'] = {'source_url': chosen, 'policy': policy}
    record['photo_policy'] = policy
    return record
