"""Publish reviewed editorial JSON as OpenCart information pages and /news.

Usage: python3 install-editorial.py /opt/energostor-next articles.json
Uses the local MariaDB socket. Never changes products, parser data or orders.
"""
from datetime import date, datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def sql(value):
    return "CONVERT(X'" + str(value).encode().hex() + "' USING utf8mb4)"


def validate(items):
    paths, titles = set(), set()
    today = datetime.now(timezone.utc).date()
    for item in items:
        slug = item['slug']
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise ValueError('Invalid article slug')
        path = item.get('path', '/news/' + slug)
        if not re.fullmatch(r'/(?:news|tpost)/[a-z0-9-]+', path):
            raise ValueError('Invalid article path')
        if path in paths or item['title'].casefold() in titles:
            raise ValueError('Duplicate article path or title')
        paths.add(path)
        titles.add(item['title'].casefold())
        if len(item['title']) > 64 or not item['summary'].strip():
            raise ValueError('Title too long or missing summary: '+item['title'])
        if date.fromisoformat(item['published']) > today:
            raise ValueError('Future publication')
        if item['kind'] not in ['Новость', 'Практика']:
            raise ValueError('Invalid editorial type')
        if item['kind'] == 'Новость' and not item.get('event_date'):
            raise ValueError('A news item needs a verified event date')
        if item.get('event_date') and date.fromisoformat(item['event_date']) > today:
            raise ValueError('Future event')
        if len(item['paragraphs']) < 3 or not item['sources']:
            raise ValueError('Article needs substantive paragraphs and sources')
        for source in item['sources']:
            parts = urlsplit(source['url'])
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                raise ValueError('Unsafe source link')
        text = ' '.join([item['title'], item['summary'], *item['paragraphs']])
        if re.search(r'merlion|мерлион|\d\s*(?:₽|руб\.|рублей|USD|EUR)', text, re.I):
            raise ValueError('Prohibited supplier mention or price')
    return items


def article_html(item, path):
    published = date.fromisoformat(item['published']).strftime('%d.%m.%Y')
    meta = [item['kind'], item['topic'], 'Опубликовано '+published]
    if item.get('event_date'):
        meta.append('Сообщение производителя: '+date.fromisoformat(item['event_date']).strftime('%d.%m.%Y'))
    if item.get('updated'):
        meta.append('Обновлено '+date.fromisoformat(item['updated']).strftime('%d.%m.%Y'))
    source_links = ''.join('<li><a href="'+escape(source['url'], quote=True)+'" target="_blank" rel="noopener noreferrer">'+escape(source['title'])+'</a></li>' for source in item['sources'])
    schema = {'@context':'https://schema.org', '@type':'NewsArticle' if item['kind']=='Новость' else 'Article',
              'headline':item['title'], 'description':item['summary'], 'datePublished':item['published'],
              'dateModified':item.get('updated', item['published']),
              'mainEntityOfPage':'https://energostor.ru'+path,
              'author':{'@type':'Organization','name':'Редакция Энергостора'},
              'publisher':{'@type':'Organization','name':'ООО «Энергостор»','url':'https://energostor.ru/'}}
    return ('<link rel="stylesheet" href="/energostor-theme/assets/css/editorial.css?v=1">'
            '<article class="ed-article"><div class="ed-meta">'+''.join('<span>'+escape(v)+'</span>' for v in meta)+'</div>'
            '<p class="ed-lead">'+escape(item['summary'])+'</p>'
            +''.join('<p>'+escape(p)+'</p>' for p in item['paragraphs'])
            +'<section class="ed-sources"><h2>Источники</h2><ul>'+source_links+'</ul>'
            '<p class="ed-note">Материал редакции Энергостора. Рекомендации редакции отделены от сообщений производителей. Характеристики конкретного исполнения проверяются по документации.</p></section>'
            '<p><a href="/news">← Новости и практика</a></p></article>'
            '<script type="application/ld+json">'+json.dumps(schema, ensure_ascii=False).replace('<', '\\u003c')+'</script>')


def main():
    root = Path(sys.argv[1]).resolve()
    if root != Path('/opt/energostor-next'):
        raise SystemExit('Only the Energostor release is supported')
    items = validate(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    items.sort(key=lambda x: (x['published'], x.get('event_date', x['published'])), reverse=True)
    migration = Path(__file__).parent
    routes_path = root / 'routes.json'
    routes = json.loads(routes_path.read_text())
    backup = root / 'editorial-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True, mode=0o700)
    home_path = root / 'upload/catalog/view/template/common/home.twig'
    home_controller = root / 'upload/catalog/controller/common/home.php'
    routing_path = root / 'catalog-routing.php'
    footer_path = root/'upload/catalog/view/template/common/footer.twig'
    for path in [routes_path, home_path, home_controller, routing_path, footer_path, root/'editorial-index.json', root/'upload/sitemap.xml']:
        if path.exists():
            shutil.copy2(path, backup / path.name)
    with (backup/'information.sql').open('w') as output:
        subprocess.run(['mysqldump','--single-transaction','energostor_next','oc_information','oc_information_description','oc_information_to_store','oc_information_to_layout'], stdout=output, check=True)

    def query(statement):
        return subprocess.check_output(['mysql','-N','-B','energostor_next','-e',statement], text=True).strip()

    next_id = int(query('SELECT COALESCE(MAX(information_id),0)+1 FROM oc_information'))
    language_ids = query('SELECT language_id FROM oc_language').splitlines()
    statements = ['START TRANSACTION;']
    index = []
    for item in items:
        path = item.get('path', '/news/'+item['slug'])
        entry = routes['routes'].get(path)
        if entry and entry['route'] != 'information/information':
            raise ValueError('Route collision: '+path)
        page_id = int(entry['value']) if entry else next_id
        if not entry:
            next_id += 1
        routes['routes'][path] = {'route':'information/information','key':'information_id','value':str(page_id)}
        statements.append(f'INSERT INTO oc_information (information_id,sort_order,status) VALUES ({page_id},200,1) ON DUPLICATE KEY UPDATE status=1;')
        for language_id in language_ids:
            values = ','.join(sql(v) for v in [item['title'],article_html(item,path),item['title']+' — Энергостор',item['summary'],''])
            statements.append(f'INSERT INTO oc_information_description (information_id,language_id,title,description,meta_title,meta_description,meta_keyword) VALUES ({page_id},{int(language_id)},{values}) ON DUPLICATE KEY UPDATE title=VALUES(title),description=VALUES(description),meta_title=VALUES(meta_title),meta_description=VALUES(meta_description),meta_keyword=VALUES(meta_keyword);')
        statements.append(f'INSERT IGNORE INTO oc_information_to_store (information_id,store_id) VALUES ({page_id},0);')
        index.append({k:v for k,v in item.items() if k not in ['paragraphs','sources']})
        index[-1].update(path=path, display_date=date.fromisoformat(item['published']).strftime('%d.%m.%Y'),
                         read_minutes=max(1,math.ceil(len(' '.join(item['paragraphs']).split())/180)))
    statements.append('COMMIT;')
    subprocess.run(['mysql','energostor_next'], input='\n'.join(statements), text=True, check=True)
    routes['routes']['/news'] = {'route':'information/news','key':'','value':''}
    routes.get('aliases',{}).pop('/news', None)
    temp = routes_path.with_suffix('.editorial.tmp')
    temp.write_text(json.dumps(routes, ensure_ascii=False))
    temp.replace(routes_path)
    (root/'editorial-index.json').write_text(json.dumps(index, ensure_ascii=False))
    for source, target in [('news.php','upload/catalog/controller/information/news.php'),('news.twig','upload/catalog/view/template/information/news.twig'),('editorial.css','upload/energostor-theme/assets/css/editorial.css')]:
        destination = root/target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(migration/source, destination)
    home = home_path.read_text()
    if not (root/'restored-design.txt').exists():
        begin = home.index('    <!-- NEWS -->')
        end = home.index('    <section class="section section--tight">', begin)
        home = home[:begin]+'''    <!-- NEWS -->
        <link rel="stylesheet" href="energostor-theme/assets/css/editorial.css?v=1">
        <section class="section news"><div class="container">
          <header class="section__head section__head--row"><h2 class="section__title">Новости и практика</h2><a class="news__all" href="news">Все материалы <span aria-hidden="true">→</span></a></header>
          <div class="ed-home-grid">{% for article in editorial_articles %}
            <a class="ed-card" href="{{ article.path|trim('/')|e('html_attr') }}">
              <div class="ed-card-meta"><span>{{ article.kind|e }} · {{ article.topic|e }}</span><span class="ed-arrow" aria-hidden="true">↗</span></div>
              <h2>{{ article.title|e }}</h2><p>{{ article.summary|e }}</p>
              <div class="ed-card-foot"><time datetime="{{ article.published|e('html_attr') }}">{{ article.display_date|e }}</time><span>{{ article.read_minutes }} мин</span></div>
            </a>{% endfor %}</div>
        </div></section>

    ''' + home[end:]
    news_link = '<li><a href="news">Новости и практика</a></li>'
    footer_anchor = '<li><a href="politika">Политика персональных данных</a></li>'
    if news_link not in home:
        home = home.replace(footer_anchor, news_link+'\n            '+footer_anchor)
    home_path.write_text(home)
    footer = footer_path.read_text()
    if news_link not in footer:
        footer_path.write_text(footer.replace(footer_anchor, news_link+'\n            '+footer_anchor))
    controller = home_controller.read_text()
    if "editorial_articles" not in controller:
        marker = "$data['energostor_base'] = HTTP_SERVER;"
        if marker not in controller:
            raise ValueError('Homepage controller changed')
        controller = controller.replace(marker, "$data['editorial_articles'] = array_slice(json_decode(file_get_contents(dirname(DIR_OPENCART) . '/editorial-index.json'), true, flags: JSON_THROW_ON_ERROR), 0, 4);\n        "+marker)
        home_controller.write_text(controller)
    routing = routing_path.read_text().replace("['product/category','product/manufacturer.info']", "['product/category','product/manufacturer.info','information/news']")
    routing_path.write_text(routing)

    # Deduplicate the imported header's repeated canonical/robots block.
    header_path = root/'upload/catalog/view/template/common/header.twig'
    header = header_path.read_text()
    editorial_style = '<link rel="stylesheet" href="energostor-theme/assets/css/editorial.css?v=1">'
    if editorial_style not in header and not (root/'restored-design.txt').exists():
        header = header.replace('</head>', editorial_style+'\n</head>')
    for line in [l for l in header.splitlines(keepends=True) if 'energostor_canonical %}' in l or 'energostor_noindex %}' in l or '<link rel="stylesheet"' in l]:
        while header.count(line) > 1:
            position = header.rfind(line)
            header = header[:position]+header[position+len(line):]
    header_path.write_text(header)

    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('', namespace)
    urls = ET.Element('{'+namespace+'}urlset')
    for path, modified in [('/news', max(a.get('updated', a['published']) for a in items))]+[(a['path'],a.get('updated',a['published'])) for a in index if a['path'].startswith('/news/')]:
        element = ET.SubElement(urls, '{'+namespace+'}url')
        ET.SubElement(element, '{'+namespace+'}loc').text = 'https://energostor.ru'+path
        ET.SubElement(element, '{'+namespace+'}lastmod').text = modified
    ET.ElementTree(urls).write(root/'upload/sitemap-news.xml', encoding='utf-8', xml_declaration=True)
    sitemap_path = root/'upload/sitemap.xml'
    sitemap = ET.parse(sitemap_path)
    target = 'https://energostor.ru/sitemap-news.xml'
    if not any(element.text==target for element in sitemap.findall('.//{'+namespace+'}loc')):
        element = ET.SubElement(sitemap.getroot(), '{'+namespace+'}sitemap')
        ET.SubElement(element, '{'+namespace+'}loc').text = target
    sitemap.write(sitemap_path, encoding='utf-8', xml_declaration=True)
    cache = root/'upload/system/storage/cache'
    for path in cache.rglob('*'):
        if path.is_file() and (path.name.startswith('cache.information.') or (path.suffix=='.php' and 'template' in path.parts)):
            path.unlink()
    settings = subprocess.check_output(['php-fpm8.3','-i'], text=True)
    if not re.search(r'^opcache.validate_timestamps => On',settings,re.M):
        subprocess.run(['systemctl','reload','php8.3-fpm'], check=True)
    print('Published',len(items),'articles. Backup:',backup)


if __name__ == '__main__':
    main()
