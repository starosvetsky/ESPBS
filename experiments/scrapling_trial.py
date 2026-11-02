"""Opt-in parser comparison. Does not write ESPBS jobs, batches or configuration."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL = 'https://vad.merlion.ru/'
SELECTOR = '.block-vendors a[href]'


def extract(html, engine):
    if engine == 'scrapling':
        from scrapling.parser import Selector
        nodes = Selector(html).css(SELECTOR)
        pairs = [(node.attrib.get('href', ''), node.css('img')) for node in nodes]
        pairs = [(href, images[0].attrib if images else {}) for href, images in pairs]
    else:
        from bs4 import BeautifulSoup
        nodes = BeautifulSoup(html, 'html.parser').select(SELECTOR)
        pairs = [(node.get('href', ''), node.select_one('img')) for node in nodes]
        pairs = [(href, image.attrs if image else {}) for href, image in pairs]
    found = {}
    for href, image in pairs:
        profile = urljoin(URL, href.strip())
        parts = urlsplit(profile)
        name = image.get('alt', '').strip()
        logo = urljoin(URL, image.get('src', '').strip())
        if (parts.netloc != 'vad.merlion.ru' or parts.query or parts.fragment
                or not re.fullmatch(r'/vendors-and-solutions/[^/]+/', parts.path)
                or not name or not image.get('src') or urlsplit(logo).scheme != 'https'):
            continue
        record = {'name': name, 'profile_url': profile, 'logo_url': logo}
        if profile in found and found[profile] != record:
            raise ValueError('Conflicting vendor card: ' + profile)
        found[profile] = record
    return sorted(found.values(), key=lambda x: x['profile_url'])


def worker(path, engine):
    import psutil
    started = time.perf_counter()
    records = extract(path.read_text(encoding='utf-8'), engine)
    elapsed = time.perf_counter() - started
    memory = psutil.Process().memory_info()
    print(json.dumps({'engine': engine, 'elapsed_seconds': elapsed,
                      'peak_rss_bytes': getattr(memory, 'peak_wset', memory.rss),
                      'memory_method': 'peak_wset' if hasattr(memory, 'peak_wset') else 'rss_at_end',
                      'records': records}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/scrapling-trial')
    parser.add_argument('--worker', choices=['bs4', 'scrapling'])
    parser.add_argument('--html', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.html, args.worker)
        return
    from espbs.universal import Client, Adapter
    client = Client(URL)
    started = time.perf_counter()
    try:
        html = client.get(URL)
    finally:
        client.close()
    fetch_seconds = time.perf_counter() - started
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = args.output / 'source.html'
    snapshot.write_text(html, encoding='utf-8')
    try:
        links, pages = Adapter().listing(html, URL)
        baseline = {'links': len(links), 'pages': len(pages)}
    except ValueError as error:
        baseline = {'error': str(error)}
    results = []
    for engine in ('bs4', 'scrapling'):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                  '--worker', engine, '--html', str(snapshot)],
                                 capture_output=True, encoding='utf-8', timeout=60)
        if process.returncode:
            raise RuntimeError(process.stderr)
        results.append(json.loads(process.stdout))
    equal = results[0]['records'] == results[1]['records']
    if not equal or not results[0]['records']:
        raise ValueError('Extractors disagree or vendor list is empty')
    records = results[0]['records']
    (args.output / 'vendors.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    for result in results:
        result['count'] = len(result.pop('records'))
    report = {'url': URL, 'html_sha256': hashlib.sha256(html.encode()).hexdigest(),
              'fetch_seconds': fetch_seconds, 'baseline': baseline, 'results': results,
              'identical_records': equal, 'fields': ['name', 'profile_url', 'logo_url'],
              'javascript_executed': False, 'runtime_modified': False}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
