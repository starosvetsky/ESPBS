"""Build a storefront snapshot from paginated server inventory JSONL, without source metadata."""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def safe_url(value):
    if not isinstance(value, str):
        return False
    u = urlsplit(value)
    host = (u.hostname or '').lower()
    return u.scheme in ('https', 'http') and host and not u.username and not u.password and not (host == 'olnisa.ru' or host.endswith('.olnisa.ru'))


def group(mpn):
    # Model families are navigation groups, not inferred technical specifications.
    prefix = re.split(r'[-/\s]', mpn.upper())[0]
    return prefix or 'Другие модели'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    models = {}
    records = 0
    rejected = 0
    for line in args.input.open(encoding='utf-8'):
        row = json.loads(line)
        p = row['product']
        brand = str(p.get('brand') or p.get('manufacturer') or '')
        if re.sub(r'[\s-]', '', brand).casefold() != 'dlink':
            rejected += 1
            continue
        records += 1
        mpn = str(p.get('mpn') or p.get('article') or p.get('sku') or '').strip()
        # Missing MPN records remain separate; never merge on a similar name.
        key = mpn if mpn else row['cursor']
        stamp = row.get('collected_at', '')
        if key in models and stamp <= models[key][0]:
            continue
        public = {k: p[k] for k in ('name', 'description', 'attributes', 'offer') if k in p}
        public.update(brand='D-Link', mpn=mpn, family=group(mpn),
                      id=hashlib.sha256(key.encode()).hexdigest()[:20],
                      images=[u for u in p.get('images', []) if safe_url(u)],
                      documents=[{'name': str(d.get('name') or 'Документ'), 'url': d['url']}
                                 for d in p.get('documents', []) if isinstance(d, dict) and safe_url(d.get('url'))])
        # Price data are retained as captured, without claiming current availability.
        if isinstance(public.get('offer'), dict):
            public['offer'] = {k: v for k, v in public['offer'].items()
                               if k in ('price', 'price_text', 'currency', 'availability')}
        models[key] = (stamp, public)
    if not models:
        raise ValueError('No verified D-Link records; refusing to create an empty storefront')
    args.output.mkdir(parents=True, exist_ok=True)
    details = args.output / 'products'
    details.mkdir(exist_ok=True)
    items = []
    for stamp, p in sorted(models.values(), key=lambda v: v[1]['mpn']):
        (details / (p['id'] + '.json')).write_text(json.dumps(p, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        items.append({k: p[k] for k in ('id', 'name', 'mpn', 'family', 'images')} | {
            'summary': str(p.get('description', ''))[:280],
            'hasSpecs': bool(p.get('attributes')), 'hasDocs': bool(p['documents'])})
    payload = {'snapshotAt': datetime.now(timezone.utc).isoformat(), 'records': records,
               'count': len(items), 'duplicates': records - len(items), 'rejected': rejected,
               'families': dict(sorted(Counter(p['family'] for p in items).items())), 'products': items}
    (args.output / 'index.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({k: v for k, v in payload.items() if k != 'products'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
