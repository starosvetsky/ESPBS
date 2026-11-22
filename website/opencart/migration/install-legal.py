"""Publish the approved company details and legal pages to the live release.

Run as root on Selectel: python3 install-legal.py /opt/energostor-next
Uses local MariaDB socket authentication; never prints database credentials.
Backs up affected information tables and changed files before publishing.
"""
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def sql(text):
    return "CONVERT(X'" + str(text).encode().hex() + "' USING utf8mb4)"


def main():
    root = Path(sys.argv[1]).resolve()
    if root != Path('/opt/energostor-next'):
        raise SystemExit('This installer targets /opt/energostor-next only')
    pages = json.loads(Path(__file__).with_name('legal-pages.json').read_text())
    routes_path = root / 'routes.json'
    routes = json.loads(routes_path.read_text())
    footer_path = root / 'upload/catalog/view/template/common/footer.twig'
    js_path = root / 'upload/energostor-theme/assets/js/main.js'
    footer = footer_path.read_text()
    js = js_path.read_text()
    old_consent = 'Даю согласие на обработку персональных данных и принимаю <a href="politika" target="_blank" rel="noopener">политику конфиденциальности</a>'
    new_consent = 'Даю <a href="consent" target="_blank" rel="noopener">согласие на обработку персональных данных</a> для ответа на обращение'
    if old_consent not in footer and new_consent not in footer:
        raise SystemExit('Consent template changed; inspect before publishing')
    old_body = "window.location.href = 'mailto:info@energostor.ru?subject='"
    if old_body not in js:
        raise SystemExit('Form handler changed; inspect before publishing')

    backup = root / 'legal-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True, mode=0o700)
    home_path = root / 'upload/catalog/view/template/common/home.twig'
    for path in [routes_path, footer_path, js_path, home_path]:
        shutil.copy2(path, backup / path.name)
    with (backup / 'information.sql').open('w') as output:
        subprocess.run(['mysqldump', '--single-transaction', 'energostor_next',
                        'oc_information', 'oc_information_description',
                        'oc_information_to_store', 'oc_information_to_layout'],
                       stdout=output, check=True)

    def query(statement):
        return subprocess.check_output(['mysql', '-N', '-B', 'energostor_next', '-e', statement], text=True).strip()

    next_id = int(query('SELECT COALESCE(MAX(information_id),0)+1 FROM oc_information'))
    language_ids = query('SELECT language_id FROM oc_language').splitlines()
    statements = ['START TRANSACTION;']
    for path, page in pages.items():
        entry = routes['routes'].get(path)
        if entry and entry['route'] != 'information/information':
            raise SystemExit('Unexpected route collision: ' + path)
        if entry:
            page_id = int(entry['value'])
        else:
            page_id = next_id
            next_id += 1
        routes['routes'][path] = {'route': 'information/information', 'key': 'information_id', 'value': str(page_id)}
        routes.get('aliases', {}).pop(path, None)
        statements.append(f'INSERT INTO oc_information (information_id,sort_order,status) VALUES ({page_id},100,1) ON DUPLICATE KEY UPDATE status=1;')
        for language_id in language_ids:
            values = ','.join(sql(v) for v in [page['title'], '<article class="legal-copy">'+page['html']+'</article>', page['title'], page['description'], ''])
            statements.append(f'INSERT INTO oc_information_description (information_id,language_id,title,description,meta_title,meta_description,meta_keyword) VALUES ({page_id},{int(language_id)},{values}) ON DUPLICATE KEY UPDATE title=VALUES(title),description=VALUES(description),meta_title=VALUES(meta_title),meta_description=VALUES(meta_description),meta_keyword=VALUES(meta_keyword);')
        statements.append(f'INSERT IGNORE INTO oc_information_to_store (information_id,store_id) VALUES ({page_id},0);')
    statements.append('COMMIT;')
    subprocess.run(['mysql', 'energostor_next'], input='\n'.join(statements), text=True, check=True)
    temporary = routes_path.with_suffix('.legal.tmp')
    temporary.write_text(json.dumps(routes, ensure_ascii=False))
    temporary.replace(routes_path)
    if '--content-only' in sys.argv:
        print('Published',len(pages),'legal texts without changing the UI. Backup:',backup)
        return
    footer = footer.replace(old_consent, new_consent).replace(' method="post" novalidate', ' method="post" enctype="text/plain"')
    footer = footer.replace('<p class="form__note">Заявка откроется в вашем почтовом приложении.</p>', '<p class="form__note">Заявка откроется в вашем почтовом приложении. Перед отправкой ознакомьтесь с <a href="politika" target="_blank" rel="noopener">политикой обработки персональных данных</a>.</p>')
    old_link = '<a href="politika">Политика конфиденциальности</a>'
    links = '<nav class="legal-links" aria-label="Правовая информация">' + ''.join('<a href="'+path[1:]+'">'+label+'</a>' for path, label in [('/politika','Персональные данные'),('/consent','Согласие'),('/cookies','Cookies'),('/requisites','Реквизиты'),('/terms','Условия работы')]) + '</nav>'
    footer = footer.replace(old_link, links)
    if 'id="legal-page-style"' not in footer:
        footer += '\n<style id="legal-page-style">.legal-links{display:flex;flex-wrap:wrap;gap:12px 24px}.footer-bottom{flex-wrap:wrap;gap:20px}.legal-copy{max-width:920px;padding-bottom:56px;line-height:1.65;font-size:17px;color:#263746}.legal-copy h2{font-size:24px;font-weight:500;margin:32px 0 14px}.legal-copy p,.legal-copy ul{margin-bottom:18px}.legal-copy a{color:#0b54a0;text-decoration:underline;text-underline-offset:3px}.legal-copy li{margin-bottom:8px}</style>\n'
    footer = footer.replace('main.js?v=20261101-hero2', 'main.js?v=legal20261122')
    footer_path.write_text(footer)
    # The imported homepage is a complete document with its own footer/dialog.
    home = home_path.read_text()
    home = home.replace(old_consent, new_consent).replace(' method="post" novalidate', ' method="post" enctype="text/plain"')
    home = home.replace('<p class="form__note">Заявка откроется в вашем почтовом приложении.</p>', '<p class="form__note">Заявка откроется в вашем почтовом приложении. Перед отправкой ознакомьтесь с <a href="politika" target="_blank" rel="noopener">политикой обработки персональных данных</a>.</p>')
    home = home.replace(old_link, links).replace('main.js?v=20261101-hero2', 'main.js?v=legal20261122')
    if 'id="legal-page-style"' not in home:
        home += footer[footer.index('<style id="legal-page-style"'):]
    home_path.write_text(home)
    metadata = "message += '\\n\\nСогласие: lead-2026-11-22; https://energostor.ru/consent; отметка пользователя: да; время подготовки письма (устройство пользователя): ' + new Date().toISOString();\n      "
    if 'Согласие: lead-2026-11-22' not in js:
        js = js.replace(old_body, metadata + old_body)
    js_path.write_text(js)
    # OpenCart caches information listings and Twig compilations.
    cache = root / 'upload/system/storage/cache'
    for path in cache.rglob('*'):
        if path.is_file() and (path.name.startswith('cache.information.') or (path.suffix == '.php' and 'template' in path.parts)):
            path.unlink()
    settings = subprocess.check_output(['php-fpm8.3','-i'], text=True)
    if not re.search(r'^opcache.validate_timestamps => On',settings,re.M):
        subprocess.run(['systemctl', 'reload', 'php8.3-fpm'], check=True)
    print('Published', len(pages), 'legal pages; backup:', backup)


if __name__ == '__main__':
    main()
