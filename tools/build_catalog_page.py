"""Convert a verified ESPBS XML export to safe static catalogue JSON."""

import argparse
import hashlib
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def value(node):
    kind = node.get('type')
    if kind == 'object':
        return {child.get('name'): value(child) for child in node}
    if kind == 'array':
        return [value(child) for child in node]
    if kind == 'null':
        return None
    if kind == 'boolean':
        return node.text == 'true'
    if kind == 'number':
        raw = node.text or '0'
        return float(raw) if any(char in raw for char in '.eE') else int(raw)
    return html.unescape(node.text or '').replace('\xa0', ' ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    parser.add_argument('xml', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    xml_bytes = args.xml.read_bytes()
    if len(xml_bytes) != manifest['xml_bytes']:
        raise ValueError('XML size differs from manifest')
    if hashlib.sha256(xml_bytes).hexdigest() != manifest['xml_sha256']:
        raise ValueError('XML checksum differs from manifest')
    root = ET.fromstring(xml_bytes)
    if root.get('batch_id') != manifest['batch_id']:
        raise ValueError('Batch ID differs from manifest')
    products = [value(node) for node in root.findall('product')]
    if len(products) != manifest['record_count']:
        raise ValueError('Record count differs from manifest')
    payload = {'manifest': manifest, 'products': products}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                           encoding='utf-8')
    print(f'Wrote {len(products)} products to {args.output}')


if __name__ == '__main__':
    main()
