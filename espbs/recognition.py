"""Domain-independent, conservative HTML discovery. No network or script execution."""
import json
import re
from collections import defaultdict, Counter
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl
from bs4 import BeautifulSoup

PRICE = re.compile(r'\d[\d\s.,\xa0]*\s*(?:₽|руб\.?|RUB\b|USD\b|EUR\b|€|\$)|[$€]\s*\d', re.I)
PAGE = re.compile(r'^(?:page|p|paged|page_number|pagen_\d+)$', re.I)
IGNORED = re.compile(r'cart|basket|checkout|login|compare|wishlist|order-sheet|add2basket', re.I)
RELATED = re.compile(r'(?:^|[-_])(?:related|recommend(?:ed|ation)?s?|upsell|cross[-_]?sell)(?:$|[-_])', re.I)
BREADCRUMB = re.compile(r'^(?:(?:bx|site)[-_])?breadcrumbs?(?:$|[-_])', re.I)
PRODUCT_CARD = re.compile(
    r'product[-_]?(?:item|card)|catalog(?:[-_]section)?[-_]item', re.I)


def clean(soup):
    result = BeautifulSoup(str(soup), 'html.parser')
    for node in result.select('script, style, nav, footer, header, aside, form, [role="navigation"], [itemprop="aggregateRating"], [itemprop="review"]'):
        if node.parent is not None:
            node.decompose()
    def auxiliary(node):
        classes = node.get('class', [])
        return any(RELATED.search(name) or BREADCRUMB.search(name) for name in classes)
    for node in list(result.find_all(auxiliary)):
        if node.parent is not None:
            node.decompose()
    return result


def value(node):
    return (node.get('content') or node.get('href') or node.get_text(' ', strip=True)).strip() if node else ''


def link(href, base):
    if not isinstance(href, str) or not href or href.startswith('#'):
        return None
    try:
        p = urlsplit(urljoin(base, href))
        if (p.scheme != 'https' or p.netloc != urlsplit(base).netloc or
                p.username or p.password or IGNORED.search(p.path + '?' + p.query) or
                any(key.lower() in ('action', 'do', 'add-to-cart') for key, _ in parse_qsl(p.query)) or
                re.search(r'\.(?:pdf|zip|jpe?g|png|svg|xlsx?|docx?)$', p.path, re.I)):
            return None
        target = urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))
        return target if target != base.split('#')[0] else None
    except ValueError:
        return None


def pairs(scope):
    """Two-column tables, definition lists and repeated CSS property rows."""
    result = []
    for node in scope.select('tr, dt, div, li')[:20000]:
        if node.select_one('input, select, button, h1, h2, h3, img'):
            continue
        if node.name == 'dt':
            sibling = node.find_next_sibling('dd')
            cells = [node, sibling] if sibling else []
        else:
            cells = node.find_all(recursive=False)
        if len(cells) != 2:
            continue
        key, val = (cell.get_text(' ', strip=True) for cell in cells)
        if 0 < len(key) <= 80 and 0 < len(val) <= 250 and key != val and any(c.isalpha() for c in key):
            pair = (key.rstrip(' :'), val)
            if pair not in result:
                result.append(pair)
    return result


def field(scope, name):
    # Do not take fields from nested recommendations or other Product scopes.
    nodes = scope.select(f'[itemprop~="{name}"]')
    values = []
    for node in nodes:
        owner = node.find_parent(attrs={'itemscope': True, 'itemtype': re.compile(r'/Product$')})
        if owner is not None and owner is not scope:
            continue
        candidate = value(node)
        if candidate and candidate not in values:
            values.append(candidate)
    return values[0] if len(values) == 1 else ''


def micro_product(soup):
    scopes = soup.select('[itemscope][itemtype$="/Product"]')
    if len(scopes) != 1:
        return {}
    scope = scopes[0]
    raw = {key: field(scope, key) for key in ('name', 'brand', 'manufacturer', 'mpn', 'sku', 'description')}
    if not raw['name']:
        return {}
    return complete(raw, scope, 'microdata')


def complete(raw, scope, method):
    attributes = pairs(scope)
    labels = {key.casefold(): val for key, val in attributes}
    for name, aliases in {
        'brand': ('бренд', 'производитель', 'brand', 'manufacturer'),
        'mpn': ('mpn', 'manufacturer part number', 'артикул производителя'),
        'sku': ('артикул', 'sku', 'код товара', 'product code'),
    }.items():
        if not raw.get(name):
            matches = {labels[label] for label in aliases if labels.get(label)}
            raw[name] = matches.pop() if len(matches) == 1 else ''
    raw['additionalProperty'] = [{'name': key, 'value': val} for key, val in attributes]
    raw['offers'] = {key: field(scope, key) for key in ('price', 'priceCurrency', 'availability')}
    raw['_recognition'] = method
    return raw


def html_product(soup, url):
    scope = clean(soup)
    structured = micro_product(scope)
    if structured:
        return structured
    headings = scope.select('h1')
    if len(headings) != 1:
        return {}
    # Restrict fields to the nearest container with both identity and facts.
    for container in headings[0].parents:
        raw = complete({'name': headings[0].get_text(' ', strip=True)}, container, 'html-evidence')
        if not (raw.get('mpn') or raw.get('sku')):
            continue
        if not raw['offers']['price'] and len(raw['additionalProperty']) < 2:
            continue
        if repeated_links(container, url):
            return {}
        return raw
    return {}


def repeated_links(scope, url):
    groups = defaultdict(list)
    for node in scope.select('tr, li, article, div')[:20000]:
        if node.parent is not None:
            groups[(id(node.parent), node.name, tuple(sorted(node.get('class', []))))].append(node)
        # Some Bitrix themes wrap every card in its own layout container.  In
        # that case sibling-only grouping cannot see the repeated collection,
        # although the cards themselves carry the same explicit product class.
        # Keep a second, page-wide group only for explicitly marked cards;
        # price/image evidence below still has to confirm every accepted row.
        classes = tuple(sorted(node.get('class', [])))
        if classes and PRODUCT_CARD.search(' '.join(classes)):
            groups[('marked-card', node.name, classes)].append(node)
    candidates = []
    for nodes in groups.values():
        if len(nodes) < 2:
            continue
        targets = []
        table = nodes[0].find_parent('table')
        heading = ' '.join(n.get_text(' ', strip=True) for n in table.select('th')).casefold() if table else ''
        product_table = bool(re.search(r'артикул|\bsku\b|\bmpn\b|код товара', heading) and
                             re.search(r'наименование|название|товар|\bname\b|\bproduct\b', heading))
        for node in nodes:
            text = node.get_text(' ', strip=True)
            marked = bool(node.get('data-product-id') or PRODUCT_CARD.search(
                ' '.join(node.get('class', []))))
            if len(text) > 2000 or not (PRICE.search(text) or node.select_one('[itemprop~="price"]') or product_table or marked and node.select_one('img')):
                continue
            anchors = node.select('a[href]')
            counts = Counter()
            for anchor in anchors:
                target = link(anchor.get('href'), url)
                if target and (anchor.get_text(strip=True) or anchor.select_one('img')):
                    counts[target] += 1 + bool(anchor.select_one('img'))
            if not counts:
                continue
            ranked = counts.most_common(2)
            if len(ranked) == 2 and ranked[0][1] == ranked[1][1]:
                continue
            targets.append(ranked[0][0])
        targets = list(dict.fromkeys(targets))
        if len(targets) >= 2:
            candidates.append(targets)
    # Prefer the largest coherent group; do not combine menus or recommendations.
    return max(candidates, key=len, default=[])


def itemlist_links(soup, url):
    found = []
    def walk(obj, depth=0):
        if depth > 20:
            return
        if isinstance(obj, list):
            for child in obj:
                walk(child, depth + 1)
        elif isinstance(obj, dict):
            kind = obj.get('@type')
            if kind == 'ItemList' or isinstance(kind, list) and 'ItemList' in kind:
                entries = obj.get('itemListElement', [])
                for entry in entries if isinstance(entries, list) else []:
                    if not isinstance(entry, dict):
                        continue
                    item = entry.get('item', entry)
                    href = item.get('url') or item.get('@id') if isinstance(item, dict) else item
                    target = link(href, url)
                    if target:
                        found.append(target)
            walk(obj.get('@graph', []), depth + 1)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.get_text()))
        except (ValueError, RecursionError):
            continue
    return list(dict.fromkeys(found))[:10000]


def pagination(soup, url):
    current = urlsplit(url)
    filters = [(key, val) for key, val in parse_qsl(current.query, keep_blank_values=True) if not PAGE.match(key)]
    result = []
    for anchor in soup.select('a[href]'):
        target = link(anchor.get('href'), url)
        if not target:
            continue
        p = urlsplit(target)
        query = parse_qsl(p.query, keep_blank_values=True)
        if (p.path == current.path and
                [(key, val) for key, val in query if not PAGE.match(key)] == filters and
                any(PAGE.match(key) and val.isdecimal() for key, val in query)):
            result.append(target)
    return list(dict.fromkeys(result))[:1000]


def category_links(soup, url):
    """Return explicit child-category links from the page content.

    Global catalogue menus are deliberately excluded by ``clean``.  This only
    accepts containers whose own class identifies them as a category children
    collection, so a crawl can follow a catalogue tree without wandering into
    neighbouring top-level departments.
    """
    scope = clean(soup)
    containers = []
    for node in scope.select('[class]'):
        classes = ' '.join(node.get('class', [])).casefold()
        if ('category' in classes or 'catalog' in classes) and any(
                marker in classes for marker in ('children', 'child-list', 'subcategor', 'sub-categor')):
            containers.append(node)
    # Keep the smallest matching containers: wrappers often contain the same
    # list and would otherwise duplicate every link.
    containers = [node for node in containers if not any(
        other is not node and node in other.parents for other in containers)]
    result = []
    for container in containers:
        for anchor in container.select('a[href]'):
            target = link(anchor.get('href'), url)
            if target and target not in result:
                result.append(target)
    return result[:10_000]


def discover(soup, url):
    structured = itemlist_links(soup, url)
    scope = clean(soup)
    if not structured:
        for product in scope.select('[itemscope][itemtype$="/Product"]'):
            node = product.select_one('a[itemprop~="url"][href], a[href]')
            target = link(node.get('href'), url) if node else None
            if target:
                structured.append(target)
    return list(dict.fromkeys(structured)) or repeated_links(scope, url), pagination(scope, url)
