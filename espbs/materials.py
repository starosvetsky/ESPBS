"""References present on a product page. Attachments are not downloaded."""
import re
from urllib.parse import urljoin, urlsplit, quote
from bs4 import BeautifulSoup
from .recognition import clean


def scope(html):
    soup = clean(BeautifulSoup(html, 'html.parser'))
    products = soup.select('[itemscope][itemtype$="/Product"]')
    if len(products) == 1:
        return products[0]
    return soup.select_one('.product-page, .product-detail, .product_detail') or soup.select_one('main') or soup


def documents(html, url):
    from .universal import public_url
    result = {}
    for a in scope(html).select('a[href]'):
        try:
            target = public_url(urljoin(url, quote(a['href'].strip(), safe=':/?=&%+#()@,;~-_')))
        except (ValueError, TypeError):
            continue
        if not re.search(r'\.(pdf|docx?|xlsx?|zip|dwg|dxf|step|stp)$', urlsplit(target).path, re.I):
            continue
        name = a.get_text(' ', strip=True) or a.get('title') or urlsplit(target).path.rsplit('/', 1)[-1]
        if target not in result:
            result[target] = {'url': target, 'name': name, 'source_url': url, 'relation': 'linked_from_product_page'}
        if len(result) >= 100:
            break
    return list(result.values())


def image_candidates(html, name):
    result = []
    for image in scope(html).select('img[src], img[data-src]'):
        alt = image.get('alt', '').strip().casefold()
        gallery = image.find_parent(class_=re.compile(r'gallery|product.image|product.photo|carousel', re.I))
        if gallery or name and alt == name.strip().casefold():
            result.append(image.get('data-src') or image.get('src'))
    return result[:30]


def coverage(record):
    fields = {key: bool(record.get(key)) for key in ('images', 'documents', 'attributes', 'description')}
    return {'fields': fields, 'missing': [key for key, present in fields.items() if not present],
            'status': 'FILLED' if all(fields.values()) else 'PARTIAL',
            'meaning': 'Field presence, not proof of correctness or source completeness'}
