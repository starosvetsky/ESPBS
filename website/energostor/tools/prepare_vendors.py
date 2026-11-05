"""Prepare a public vendor directory from the internal source snapshot."""
import concurrent.futures
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parents[1]
INTERNAL = ROOT.parent / '.tmp'
DEST = ROOT / 'vendors'
LOGOS = DEST / 'logos'
LOGOS.mkdir(parents=True, exist_ok=True)
source = json.loads((INTERNAL / 'vendors-complete-internal.json').read_text(encoding='utf-8'))
vendors = {}
for item in source:
    name = item['name'].strip()
    if not name or re.search('merlion|мерлион', name, re.I):
        continue
    vendors.setdefault(name.casefold(), item)


def prepare(item):
    name, url = item['name'], item['logo']
    identity = hashlib.sha256(name.casefold().encode()).hexdigest()[:20]
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif'):
        return {'id': identity, 'name': name, 'logo': None}
    path = LOGOS / (identity + suffix)
    if path.exists() and path.stat().st_size:
        return {'id': identity, 'name': name, 'logo': 'logos/' + path.name}
    try:
        assert urlsplit(url).hostname == 'static.lc-group.ru'
        with urllib.request.urlopen(quote(url, safe=':/?=&%'), timeout=15) as response:
            data = response.read(4_000_001)
        assert 0 < len(data) <= 4_000_000
        if suffix == '.svg':
            text = data.decode('utf-8-sig')
            ET.fromstring(text)
            assert not re.search(r'<script|<foreignObject|\bon\w+\s*=|(?:href|src)\s*=\s*["\'](?:https?:|//|javascript:)', text, re.I)
            text = re.sub(r'<!--.*?-->|<metadata\b.*?</metadata>', '', text, flags=re.S | re.I)
            assert not re.search('merlion|мерлион', text, re.I)
            data = text.encode('utf-8')
        else:
            from PIL import Image
            from io import BytesIO
            with Image.open(BytesIO(data)) as image:
                image.verify()
        path.write_bytes(data)
        return {'id': identity, 'name': name, 'logo': 'logos/' + path.name}
    except Exception:
        return {'id': identity, 'name': name, 'logo': None}


result = []
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for item in pool.map(prepare, vendors.values()):
        result.append(item)
        if len(result) % 100 == 0:
            print(f'Prepared {len(result)}/{len(vendors)}', flush=True)
payload = {'count': len(result), 'vendors': result}
(DEST / 'data.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
print('Complete:', len(result), 'with logos:', sum(bool(v['logo']) for v in result), flush=True)
