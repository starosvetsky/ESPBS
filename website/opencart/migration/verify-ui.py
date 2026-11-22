"""Read-only route and markup audit of the live Energostor UI.

Run on the server after install-ui.py. Covers every category, brand and
information URL plus representative products, search and 404 behaviour.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlsplit
import posixpath

ROOT = Path('/opt/energostor-next')
CTX = ssl.create_default_context()


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        self.sock = CTX.wrap_socket(socket.create_connection(('127.0.0.1',443), timeout=25), server_hostname='energostor.ru')


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.canonicals, self.hrefs, self.h1 = [], [], 0
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'h1': self.h1 += 1
        if tag == 'a' and 'href' in attributes: self.hrefs.append(attributes['href'])
        if tag == 'link' and attributes.get('rel') == 'canonical': self.canonicals.append(attributes.get('href'))


def fetch(path, depth=0):
    connection = LocalHTTPS('energostor.ru', timeout=25, context=CTX)
    try:
        connection.request('GET', path, headers={'Host':'energostor.ru','User-Agent':'Energostor-UI-Verification/1.0'})
        response = connection.getresponse()
        status, html = response.status, response.read().decode('utf-8','replace')
        if status in [301,302] and depth < 4:
            target = urlsplit(response.getheader('Location',''))
            if target.hostname not in [None,'energostor.ru','www.energostor.ru']: raise ValueError('Unexpected offsite redirect')
            return fetch(target.path + ('?'+target.query if target.query else ''),depth+1)
        return status, html
    finally:
        connection.close()


def main():
    data = json.loads((ROOT/'routes.json').read_text())
    routes = data['routes']
    paths = ['/']+[path for path, route in routes.items() if route['route'] != 'product/product']
    product_index = {route['value']:path for path,route in routes.items() if route['route']=='product/product'}
    rich = [product_index[pid] for pid,media in data['media'].items() if pid in product_index and (media.get('images') or media.get('documents'))]
    products = [path for path,route in routes.items() if route['route']=='product/product']
    paths += rich[:15] + products[::max(1,len(products)//25)][:25]
    paths += ['/index.php?route=product/search&search=D-Link','/index.php?route=product/search&search=ZXZZNONEXISTENT50921','/index.php?route=product/search']
    paths = list(dict.fromkeys(paths))
    if '--retired-only' in sys.argv: paths = []
    allowed = set(routes) | set(data.get('aliases',{})) | {'/','/index.php','/sitemap.xml','/sitemap-news.xml'}
    failures, dead_links = [], set()

    def check(path):
        status, html = fetch(path)
        issues = []
        if status != 200: issues.append('HTTP '+str(status))
        if '<footer class="ui-footer">' not in html: issues.append('missing shared footer')
        if html.count('id="site-header"') != 1: issues.append('header count')
        if html.count('id="lead-form"') != 1: issues.append('form count')
        if 'ui.css?v=' not in html or 'ui.js?v=' not in html: issues.append('missing UI assets')
        if 'name="consent" required' not in html: issues.append('missing consent')
        if 'Fatal error' in html or 'Stack trace:' in html: issues.append('runtime exception')
        if path=='/index.php?route=product/search&search=D-Link' and 'class="ui-product-row"' not in html: issues.append('brand search lost existing products')
        if 'search=ZXZZNONEXISTENT50921' in path and 'class="ui-product-row"' in html: issues.append('empty search returned unrelated products')
        markup = Markup(html)
        if markup.h1 != 1: issues.append('h1 count '+str(markup.h1))
        if not path.startswith('/index.php') and len(markup.canonicals) != 1: issues.append('canonical count')
        unknown = []
        for href in markup.hrefs:
            link = urlsplit(href)
            if link.scheme and link.scheme not in ['http','https']: continue
            if link.hostname and link.hostname not in ['energostor.ru','www.energostor.ru']: continue
            linked_path = posixpath.normpath('/'+link.path.lstrip('/')).rstrip('/') or '/'
            if linked_path not in allowed and not any(linked_path.lower().endswith(ext) for ext in ['.pdf','.png','.jpg','.webp','.svg','.zip','.jpeg']): unknown.append(linked_path)
        return path, issues, unknown

    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(check,path):path for path in paths}
        for count, job in enumerate(as_completed(jobs), 1):
            path = jobs[job]
            try:
                _, issues, unknown = job.result()
                if issues: failures.append({'path':path,'issues':issues})
                dead_links.update(unknown)
            except Exception as error:
                failures.append({'path':path,'issues':[str(error)]})
            if count % 50 == 0: print('Checked', count, '/', len(paths), flush=True)
    status, html = fetch('/this-page-does-not-exist-ui-check')
    if status != 404 or '<footer class="ui-footer">' not in html: failures.append({'path':'404','issues':[str(status)]})
    retired = [path for path,target in data.get('aliases',{}).items() if target=='']
    for path in retired:
        status,html = fetch(path)
        if status!=410 or '<footer class="ui-footer">' not in html: failures.append({'path':path,'issues':['retired page '+str(status)]})
    report = {'checked':len(paths)+1+len(retired),'failures':failures,'unknown_internal_links':sorted(dead_links)}
    target = ROOT/('ui-verification-retired.json' if '--retired-only' in sys.argv else 'ui-verification.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
