"""Prepare the isolated OpenCart release database and URL map from a read-only snapshot."""
import argparse
from html import escape
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from datetime import date
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape


ORIGIN = 'https://energostor.ru'
DATABASE = 'energostor_next'
MONEY = re.compile(r'(?:\d[\d\s.,]*\s*(?:₽|руб(?:\.|лей|ля)?\b|RUB\b|USD\b|EUR\b|\$|€)|[\$€₽]\s*\d[\d\s.,]*)', re.I)
PRICE_LABEL = re.compile(r'(?:^|\b)(?:цена|стоимость|price|discount|скидка)(?:\b|$)', re.I)
SLUG = re.compile(r'[^a-z0-9]+')


def text_value(value):
    return "CONVERT(X'" + str(value).encode().hex() + "' USING utf8mb4)"


def clean(text):
    return MONEY.sub('', text or '').strip()


def urls(value):
    accepted = []
    for item in json.loads(value):
        link = item if isinstance(item,str) else item.get('url','') if isinstance(item,dict) else ''
        try:
            parts = urlsplit(link)
        except ValueError:
            continue
        if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password:
            host = parts.hostname.lower()
            if host != 'olnisa.ru' and not host.endswith('.olnisa.ru'):
                accepted.append(link)
    return list(dict.fromkeys(accepted))


def confirmed_identity(row):
    brand = ' '.join(row['brand'].split()).casefold()
    return brand + '|' + row['mpn'].strip() if brand and row['mpn'] else ''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--legacy', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pages = json.loads(args.legacy.read_text(encoding='utf-8'))
    sql_path = args.output / 'release.sql'
    state = {'routes': {}, 'aliases': {}, 'media': {}, 'sections': []}
    canonical = state['routes']
    sitemap = ['/']
    attributes = {}
    count = 0
    merged = 0
    with sqlite3.connect(args.snapshot.resolve().as_uri()+'?mode=ro', uri=True) as source, sql_path.open('w',encoding='utf-8') as sql:
        source.row_factory = sqlite3.Row
        source.execute('BEGIN')

        def run(statement):
            sql.write(statement+';\n')

        def insert(table, columns, *values):
            fields = ','.join(str(x) if isinstance(x,int) else text_value(x) for x in values)
            run(f'INSERT INTO oc_{table} ({columns}) VALUES ({fields})')

        def route(path, name, key='', value='', index=True):
            if path in canonical:
                raise ValueError(f'Conflicting public URL {path}')
            canonical[path] = {'route': name, 'key':key, 'value': str(value)}
            if index:
                sitemap.append(path)

        run('START TRANSACTION')
        for table in (
            'product','product_description','product_to_category','product_to_store','product_code',
            'product_image','product_attribute','product_discount','product_related','product_option',
            'product_option_value','product_to_layout','product_reward','product_subscription',
            'category','category_description','category_path','category_to_store','category_to_layout',
            'manufacturer','manufacturer_to_store','seo_url','information','information_description',
            'information_to_store','information_to_layout','layout_module','attribute',
            'attribute_description','attribute_group','attribute_group_description',
        ):
            run('DELETE FROM oc_'+table)
        run("UPDATE oc_setting SET value='0' WHERE `key` IN ('config_seo_url','config_review_status','config_tax','config_stock_display','config_stock_checkout','config_error_display')")
        for key, value in {
            'config_name':'Энергостор', 'config_meta_title':'Энергостор — снабжение предприятий инженерным оборудованием',
            'config_meta_description':'Поставка электротехнического, промышленного и сетевого оборудования. Подбор по артикулу и комплектация по спецификации.',
            'config_email':'info@energostor.ru', 'config_telephone':'+7 (812) 200-93-40',
            'config_address':'Санкт-Петербург, ул. Ивана Черных, д. 29 литера А, офис 317',
        }.items():
            run('DELETE FROM oc_setting WHERE store_id=0 AND BINARY `key`='+text_value(key))
            insert('setting','store_id,code,`key`,value,serialized',0,'config',key,value,0)

        insert('attribute_group','attribute_group_id,sort_order',10000,0)
        insert('attribute_group_description','attribute_group_id,language_id,name',10000,1,'Характеристики')
        route('/catalog','information/catalog')
        route('/brands','product/manufacturer')
        route('/vendors','information/catalog.vendors')
        route('/sitemap','information/sitemap',index=False)
        category_ids = {}
        category_paths = {}
        for cid, row in enumerate(source.execute('SELECT slug,title,position,products,NULL parent FROM parents UNION ALL SELECT slug,title,position,products,parent FROM children ORDER BY parent,position,slug'),10000):
            if not row['products']:
                continue
            slug, title, pos, total, parent = row
            parent_id = category_ids[parent] if parent else 0
            path = f'{parent_id}_{cid}' if parent else str(cid)
            url = '/catalog/'+slug
            category_paths[slug] = url
            category_ids[slug] = cid
            route(url,'product/category','path',path)
            state['sections'].append(dict(slug=slug,title=title,parent=parent,count=total,url=url))
            insert('category','category_id,parent_id,sort_order,status,image',cid,parent_id,pos,1,'')
            insert('category_description','category_id,language_id,name,meta_title,meta_description,meta_keyword,description',
                   cid,1,title,title+' — каталог Энергостора',title+'. Оборудование и комплектующие в каталоге Энергостора. Подбор по артикулу и спецификации.','','')
            insert('category_to_store','category_id,store_id',cid,0)
            if parent:
                insert('category_path','category_id,path_id,level',cid,parent_id,0)
            insert('category_path','category_id,path_id,level',cid,cid,int(bool(parent)))

        brands = {}
        for mid, row in enumerate(source.execute('SELECT * FROM brands WHERE products>0 ORDER BY slug'),10000):
            name = row['title'][:64]
            brands[row['slug']] = mid
            route('/brand/'+row['slug'],'product/manufacturer.info','manufacturer_id',mid)
            insert('manufacturer','manufacturer_id,name,image',mid,name,'')
            insert('manufacturer_to_store','manufacturer_id,store_id',mid,0)

        # Keep the stable URL of the confirmed record. A duplicate can supply missing media.
        duplicate_groups = {}
        for candidate in source.execute("SELECT * FROM products WHERE dedupe_key IS NULL AND brand<>'' AND mpn<>''"):
            identity = confirmed_identity(candidate)
            winner = source.execute('SELECT id FROM products WHERE dedupe_key=?', (identity,)).fetchone()
            if winner:
                duplicate_groups.setdefault(winner['id'], []).append(dict(candidate))
        skipped_ids = {entry['id'] for group in duplicate_groups.values() for entry in group}
        merged = len(skipped_ids)

        for pid,row in enumerate(source.execute('SELECT * FROM products ORDER BY id'),10000):
            if row['id'] in skipped_ids:
                continue
            name = clean(row['name'])[:255] or row['mpn'][:255] or 'Оборудование'
            mpn = row['mpn']
            brand = row['brand']
            title = f'{name} — Энергостор'[:255]
            desc = clean(row['summary'])[:160] or f'{name}. Подбор и поставка оборудования по спецификации.'[:160]
            description = escape(clean(row['description'])).replace('\n','<br>')
            images = urls(row['images'])
            documents = urls(row['documents'])
            for duplicate in duplicate_groups.get(row['id'], []):
                images = list(dict.fromkeys(images + urls(duplicate['images'])))
                documents = list(dict.fromkeys(documents + urls(duplicate['documents'])))
            if images or documents:
                state['media'][str(pid)] = dict(images=images,documents=documents)
            keyword = SLUG.sub('-',mpn.lower()).strip('-')[:65]
            url = '/product/'+((keyword+'-') if keyword else '')+row['id']
            # Keep records without a confirmed brand and MPN accessible without indexing thin duplicates.
            indexable = bool(row['dedupe_key'] and (row['description'] or row['has_attrs'] or images))
            route(url,'product/product','product_id',pid,index=indexable)
            if not indexable:
                canonical[url]['noindex'] = True
            insert('product','product_id,model,manufacturer_id,date_available,status,shipping,image,location,date_added,date_modified',
                   pid,(mpn or row['id'])[:64],brands.get(row['brand_slug'],0),'2020-01-01',1,0,'','',date.today().isoformat(),date.today().isoformat())
            insert('product_description','product_id,language_id,name,description,tag,meta_title,meta_description,meta_keyword',
                   pid,1,name,description,mpn,title,desc,'')
            insert('product_to_store','product_id,store_id',pid,0)
            for slug in dict.fromkeys((row['parent'],row['child'])):
                if slug in category_ids:
                    insert('product_to_category','product_id,category_id',pid,category_ids[slug])
            if mpn:
                insert('product_code','product_id,code,value',pid,'sku',mpn[:255])
            seen = set()
            candidates = [row, *duplicate_groups.get(row['id'], [])]
            for attr in (a for candidate in candidates for a in json.loads(candidate['attributes'])):
                label = attr['label'][:64]
                if not label or PRICE_LABEL.search(label) or label in seen:
                    continue
                seen.add(label)
                if label not in attributes:
                    aid = len(attributes)+10000
                    attributes[label] = aid
                    insert('attribute','attribute_id,attribute_group_id,sort_order',aid,10000,0)
                    insert('attribute_description','attribute_id,language_id,name',aid,1,label)
                insert('product_attribute','product_id,attribute_id,language_id,text',pid,attributes[label],1,clean(attr['value'])[:12000])
            count += 1

        for page_id,(path,page) in enumerate(sorted(pages.items()),10000):
            if 'redirect' in page or page.get('retired'):
                state['aliases'][path] = page.get('redirect', '')
                continue
            title = page['title'].strip() or path.strip('/')
            if page.get('product'):
                pid = 900000 + page_id
                route(path, 'product/product', 'product_id', pid)
                insert('product','product_id,model,date_available,status,shipping,image,location',pid,'MOTORSURG','2020-01-01',1,0,'','')
                insert('product_description','product_id,language_id,name,description,tag,meta_title,meta_description,meta_keyword',
                       pid,1,title,'','MOTORSURG',title+' — Энергостор',title+'. Запросить коммерческое предложение.', '')
                insert('product_to_store','product_id,store_id',pid,0)
                state['media'][str(pid)] = {'images':urls(json.dumps(page.get('images',[]))), 'documents':[]}
                count += 1
                continue
            html = page['html']
            if not html.strip():
                raise ValueError(f'Missing content from {path}')
            description = page['description'] or re.sub(r'<[^>]*>',' ',html)
            description = re.sub(r'\s+',' ',description).strip()[:160]
            route(path,'information/information','information_id',page_id,index=path != '/politika')
            if path == '/politika':
                canonical[path]['noindex'] = True
            insert('information','information_id,sort_order,status',page_id,0,1)
            insert('information_description','information_id,language_id,title,description,meta_title,meta_description,meta_keyword',
                   page_id,1,title[:64],html,title[:255],description,'')
            insert('information_to_store','information_id,store_id',page_id,0)
        state['aliases'].update({
            '/catalog.html':'/catalog', '/catalog/d-link':'/brand/d-link',
            '/members/login':'/contacts', '/sitemap-store.xml':'/sitemap.xml',
        })
        run('COMMIT')
    (args.output/'routes.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8')
    for index in range(0,len(sitemap),30000):
        paths = sitemap[index:index+30000]
        entries = '\n'.join('<url><loc>'+xml_escape(ORIGIN+path)+'</loc></url>' for path in paths)
        (args.output/f'sitemap-{index//30000+1}.xml').write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'+entries+'\n</urlset>\n', encoding='utf-8')
    entries = ''.join('<sitemap><loc>'+ORIGIN+f'/sitemap-{n}.xml</loc></sitemap>' for n in range(1,(len(sitemap)-1)//30000+2))
    (args.output/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+entries+'</sitemapindex>\n',encoding='utf-8')
    print(f'{count} products, {merged} confirmed duplicates merged, {len(category_ids)} categories, {len(brands)} brands, {len(sitemap)} indexable URLs')


if __name__ == '__main__':
    main()
