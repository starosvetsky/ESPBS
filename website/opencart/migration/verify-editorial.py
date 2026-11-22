"""Read-only live checks for the published editorial release, run on Selectel."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.canonicals, self.links, self.headings = [], [], 0
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'h1':
            self.headings += 1
        if tag == 'link' and attributes.get('rel') == 'canonical':
            self.canonicals.append(attributes.get('href'))
        if tag == 'a':
            self.links.append(attributes.get('href'))


def fetch(path):
    result = subprocess.run(['curl','--resolve','energostor.ru:443:127.0.0.1','-sS','-w','\n%{http_code}','https://energostor.ru'+path], capture_output=True, text=True, check=True)
    html, status = result.stdout.rsplit('\n', 1)
    assert status == '200', (path, status)
    return html


root = Path('/opt/energostor-next')
articles = json.loads((root/'articles.json').read_text())
index = fetch('/news')
page = Page(index)
assert page.headings == 1 and page.canonicals == ['https://energostor.ru/news']
for article in articles:
    path = article.get('path', '/news/'+article['slug'])
    html = fetch(path)
    page = Page(html)
    assert page.headings == 1, path
    assert page.canonicals == ['https://energostor.ru'+path], (path, page.canonicals)
    assert 'application/ld+json' in html and 'ed-article' in html
    for source in article['sources']:
        assert source['url'] in page.links, (path, source['url'])
    print('OK', path)
home = fetch('/')
assert home.count('class="ed-card"') == 4
assert 'href="news"' in home and 'Все материалы' in home
assert 'news-card__img' not in home
assert 'Новости и практика' in fetch('/catalog')
ET.fromstring(fetch('/sitemap-news.xml'))
assert 'sitemap-news.xml' in fetch('/sitemap.xml')
assert 'Bootstrap makes' in fetch('/energostor-theme/assets/css/editorial.css')
assert '7805783999' in fetch('/politika')
print('PASS:', len(articles), 'articles, home, index, catalogue, sitemap, legal page and CSS')
