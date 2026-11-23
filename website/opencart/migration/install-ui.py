"""Install the unified Energostor UI without changing catalogue or orders.

Run on Selectel: python3 /opt/energostor-next/install-ui.py /opt/energostor-next
The sibling ui/ folder contains the reviewed source. Existing files are backed
up outside webroot; published catalogue data and legal text are preserved.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import json
import xml.etree.ElementTree as ET


def main():
    root = Path(sys.argv[1]).resolve()
    if root != Path('/opt/energostor-next'):
        raise SystemExit('This installer targets /opt/energostor-next only')
    if (root/'restored-design.txt').exists():
        raise SystemExit('Owner restored the PDF reference design. Do not reinstall the superseded UI shell; use restore-design.py for presentation updates.')
    source = Path(__file__).parent/'ui'
    public = root/'upload'
    templates = public/'catalog/view/template'
    controllers = public/'catalog/controller'
    previous_header = (templates/'common/header.twig').read_text()
    previous_footer = (templates/'common/footer.twig').read_text()
    previous_home = (templates/'common/home.twig').read_text()
    backup = root/'ui-backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True, mode=0o700)
    mutations = {}

    def put(path, text):
        mutations[path] = text

    # Preserve the existing hover images/taxonomy integration and legal consent.
    menu_start = previous_header.index('<div class="mega nav-browser"')
    depth = 0
    menu_end = None
    for match in re.finditer(r'<div\b[^>]*>|</div\s*>', previous_header[menu_start:]):
        depth += -1 if match.group().startswith('</') else 1
        if depth == 0:
            menu_end = menu_start + match.end()
            break
    if menu_end is None:
        raise SystemExit('Catalogue menu is unbalanced')
    menu = previous_header[menu_start:menu_end]
    dialog = re.search(r'<dialog\b.*?</dialog>', previous_footer, re.S)
    if not dialog or 'name="consent" required' not in dialog.group():
        raise SystemExit('Expected the published consent form before the UI install')
    header = (source/'header.twig').read_text().replace('__CATALOG_MENU__', menu)
    footer = (source/'footer.twig').read_text().replace('__LEAD_DIALOG__', dialog.group())
    if '{{ header }}' in previous_home and '<!-- NEWS -->' in previous_home:
        home = previous_home
    else:
        main_match = re.search(r'<main\b[^>]*>(.*?)</main>', previous_home, re.S)
        if not main_match:
            raise SystemExit('Homepage content not found; stop before mutating files')
        home = '{{ header }}\n'+main_match.group(1)+'\n{{ footer }}\n'
    # The six original directions remain useful; only the common shell changes.
    put(templates/'common/home.twig', home)
    put(templates/'common/header.twig', header)
    put(templates/'common/footer.twig', footer)
    mappings = {'crumbs.twig':'ui/crumbs.twig','sidebar.twig':'ui/sidebar.twig','macros.twig':'ui/macros.twig',
                'catalog.twig':'information/catalog.twig','listing.twig':'ui/listing.twig',
                'thumb.twig':'product/thumb.twig','product.twig':'product/product.twig',
                'information.twig':'information/information.twig','brands.twig':'product/manufacturer_list.twig',
                'sitemap.twig':'information/sitemap.twig','not_found.twig':'error/not_found.twig','gone.twig':'error/gone.twig','pagination.twig':'common/pagination.twig'}
    for name, target in mappings.items():
        put(templates/target, (source/name).read_text())
    for name in ['category','manufacturer_info','search']:
        put(templates/f'product/{name}.twig', "{% include 'catalog/view/template/ui/listing.twig' %}\n")
    put(public/'energostor-theme/assets/css/ui.css', (source/'ui.css').read_text())
    put(public/'energostor-theme/assets/css/home-layout.css', (source/'home-layout.css').read_text())
    put(public/'energostor-theme/assets/js/ui.js', (source/'ui.js').read_text())
    put(root/'ui-helpers.php', (source/'ui-helpers.php').read_text())
    routing_path = root/'catalog-routing.php'
    routing = routing_path.read_text()
    retired = """http_response_code(410);
        header('Content-Type: text/plain; charset=UTF-8');
        echo 'Страница удалена.';
        exit;"""
    routing = routing.replace(retired, "$_GET['route'] = 'error/gone';\n        return;")
    if "require_once __DIR__ . '/ui-helpers.php';" not in routing:
        routing += "\nrequire_once __DIR__ . '/ui-helpers.php';\n"
    put(routing_path, routing)
    put(controllers/'error/gone.php',(source/'gone.php').read_text())

    for name, kind in [('category','category'),('manufacturer','brand'),('search','search')]:
        path = controllers/f'product/{name}.php'
        content = path.read_text()
        view = 'manufacturer_info' if name == 'manufacturer' else name
        marker = f"$this->response->setOutput($this->load->view('product/{view}', $data));"
        if marker not in content:
            raise SystemExit('Controller output changed: '+name)
        if f"$data['ui_listing_type'] = '{kind}';" not in content:
            extra = f"""$data['ui_sections'] = energostorUiSections();
            $data['ui_listing_type'] = '{kind}';
            $data['ui_product_total'] = $product_total ?? 0;
            $data['sorts'] = energostorUiSorts($data['sorts'] ?? []);
            $data['results'] = 'Показано ' . (($product_total ?? 0) ? (($page - 1) * $limit + 1) : 0) . '–' . min($page * $limit, $product_total ?? 0) . ' из ' . number_format($product_total ?? 0, 0, ',', ' ');
            """
            content = content.replace(marker, extra+marker)
        put(path, content)

    path = controllers/'product/thumb.php'
    content = path.read_text()
    marker = "return $this->load->view('product/thumb', $data);"
    if "$data['ui_brand']" not in content:
        content = content.replace(marker, """static $uiBrands = null;
        if ($uiBrands === null) {
            $uiBrands = array_column($this->db->query('SELECT manufacturer_id, name FROM ' . DB_PREFIX . 'manufacturer')->rows, 'name', 'manufacturer_id');
        }
        $data['ui_brand'] = $uiBrands[$data['manufacturer_id'] ?? 0] ?? '';
        """+marker)
    put(path, content)
    path = controllers/'product/manufacturer.php'
    content = mutations[path]
    marker = "$this->response->setOutput($this->load->view('product/manufacturer_list', $data));"
    if "energostorUiBrandGroups" not in content:
        content = content.replace(marker, "$data['categories'] = energostorUiBrandGroups($data['categories'] ?? [], $this->db);\n        "+marker)
    marker = "$manufacturer_info = $this->model_catalog_manufacturer->getManufacturer($manufacturer_id);"
    if "uiCanonicalManufacturer" not in content:
        extra = """$uiBrandMap = energostorUiBrands($this->db);
        $uiCanonicalManufacturer = $uiBrandMap[$manufacturer_id]['canonical'] ?? $manufacturer_id;
        if ($uiCanonicalManufacturer !== $manufacturer_id) {
            $this->response->redirect($this->url->link('product/manufacturer.info', 'manufacturer_id=' . $uiCanonicalManufacturer), 301);
            return null;
        }
        """
        content = content.replace(marker, extra+marker+"\n        if ($manufacturer_info) $manufacturer_info['name'] = energostorUiBrandName($manufacturer_id, $this->db);")
    put(path, content)
    path = public/'catalog/model/catalog/product.php'
    content = path.read_text()
    original_filter = """$sql .= " AND `p`.`manufacturer_id` = '" . (int)$data['filter_manufacturer_id'] . "'";"""
    replacement = """$sql .= " AND `p`.`manufacturer_id` IN (" . implode(',', energostorUiManufacturerIds((int)$data['filter_manufacturer_id'], $this->db)) . ")";"""
    if replacement not in content:
        if content.count(original_filter) != 2:
            raise SystemExit('Expected product and total manufacturer filters')
        content = content.replace(original_filter,replacement)
    search_marker = '\n\t\t\t$sql .= ")";\n\t\t}\n\n\t\tif (!empty($data[\'filter_manufacturer_id\']))'
    if 'energostorUiSearchSql' not in content:
        if content.count(search_marker)!=2:
            raise SystemExit('Expected matching search clauses for products and total')
        content = content.replace(search_marker, "\n\t\t\tif (!empty($data['filter_search'])) $sql .= ' OR ' . energostorUiSearchSql((string)$data['filter_search'], $this->db);"+search_marker)
    put(path, content)
    path = controllers/'product/product.php'
    content = path.read_text()
    marker = "$this->response->setOutput($this->load->view('product/product', $data));"
    if "uiCanonicalBrand" not in content:
        content = content.replace(marker, """$uiBrandMap = energostorUiBrands($this->db);
            $uiCanonicalBrand = $uiBrandMap[(int)$product_info['manufacturer_id']]['canonical'] ?? (int)$product_info['manufacturer_id'];
            $data['manufacturer'] = energostorUiBrandName((int)$product_info['manufacturer_id'], $this->db);
            $data['manufacturers'] = $this->url->link('product/manufacturer.info', 'manufacturer_id=' . $uiCanonicalBrand);
            """+marker)
    put(path, content)
    path = controllers/'product/thumb.php'
    content = mutations[path]
    content = content.replace("$data['ui_brand'] = $uiBrands[$data['manufacturer_id'] ?? 0] ?? '';", "$data['ui_brand'] = energostorUiBrandName((int)($data['manufacturer_id'] ?? 0), $this->db);")
    put(path, content)
    path = controllers/'information/information.php'
    content = path.read_text()
    marker = "$this->response->setOutput($this->load->view('information/information', $data));"
    if "$data['ui_page_path']" not in content:
        if marker not in content:
            raise SystemExit('Information controller changed')
        content = content.replace(marker, "$data['ui_page_path'] = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);\n            "+marker)
    if 'energostorUiRichtext' not in content:
        content = content.replace(marker, "$data['description'] = energostorUiRichtext($data['description']);\n            "+marker)
    put(path, content)
    path = templates/'information/vendors.twig'
    put(path, path.read_text().replace('href="../"','href="./"'))
    for relative, title in [('error/not_found.php','Страница не найдена — Энергостор'),('information/sitemap.php','Карта сайта — Энергостор')]:
        path = controllers/relative
        content = path.read_text()
        content = content.replace("$this->document->setTitle($this->language->get('heading_title'));", "$this->document->setTitle('"+title+"');")
        put(path,content)
    path = controllers/'product/search.php'
    content = mutations[path]
    if "$this->config->set('config_product_search', 'and');" not in content:
        language_marker = "$this->load->language('product/search');"
        if language_marker not in content: raise SystemExit('Search controller changed')
        content = content.replace(language_marker, language_marker+"\n        $this->config->set('config_product_search', 'and');")
    marker = "$data['header'] = $this->load->controller('common/header');"
    if 'Поиск оборудования — Энергостор' not in content:
        content = content.replace(marker, "$this->document->setTitle(!empty($data['search']) ? 'Поиск «' . $data['search'] . '» — Энергостор' : 'Поиск оборудования — Энергостор');\n        "+marker)
    put(path,content)
    path = controllers/'common/home.php'
    content = path.read_text()
    marker = "$data['header'] = $this->load->controller('common/header');"
    if 'Энергостор — инженерное оборудование для предприятий' not in content:
        content = content.replace(marker, "$this->document->setTitle('Энергостор — инженерное оборудование для предприятий');\n        $this->document->setDescription('Комплексное снабжение предприятий и строительных объектов. Электротехническое, промышленное и сетевое оборудование. Подбор по спецификациям.');\n        "+marker)
    put(path,content)
    path = controllers/'information/information.php'
    content = mutations[path]
    content = content.replace("$this->document->setDescription($information_info['meta_description']);", "$this->document->setDescription(str_replace('Энерготорг', 'Энергостор', $information_info['meta_description']));")
    put(path,content)
    # Remove only mechanically confirmed manufacturer aliases from sitemap files.
    # All original routes remain available and redirect through the controller.
    raw_brands = subprocess.check_output(['mysql','-N','-B','energostor_next','-e','SELECT manufacturer_id, HEX(name) FROM oc_manufacturer'],text=True)
    brand_names = {int(line.split('\t')[0]):bytes.fromhex(line.split('\t')[1]).decode('utf-8') for line in raw_brands.splitlines()}
    by_name = {name.strip().casefold():bid for bid,name in brand_names.items()}
    aliases = {}
    for bid, name in brand_names.items():
        match = re.fullmatch(r'(.+?)\s+Диаметр,\s*мм\s*[—-]\s*\d+(?:[.,]\d+)?',name)
        prefix = re.fullmatch(r'Производитель:\s*(.+)',name)
        clean = match.group(1).strip() if match else prefix.group(1).strip() if prefix else name
        canonical = by_name.get(clean.casefold(),bid)
        if canonical != bid: aliases[bid] = canonical
    release = json.loads((root/'routes.json').read_text())
    alias_urls = {'https://energostor.ru'+path for path,entry in release['routes'].items() if entry['route']=='product/manufacturer.info' and int(entry['value']) in aliases}
    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    ET.register_namespace('', namespace)
    for path in public.glob('sitemap-*.xml'):
        tree = ET.parse(path)
        removed = False
        for entry in list(tree.getroot()):
            if entry.findtext('{'+namespace+'}loc') in alias_urls:
                tree.getroot().remove(entry)
                removed = True
        if removed: put(path, ET.tostring(tree.getroot(), encoding='unicode', xml_declaration=True))
    # All preparation above is non-mutating. Save an exact rollback set first.
    manifest = []
    for path, text in mutations.items():
        relative = path.relative_to(root)
        if path.exists():
            target = backup/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        manifest.append({'path':str(relative),'existed':path.exists()})
    (backup/'manifest.txt').write_text('\n'.join(str(m) for m in manifest))
    for index, (path, text) in enumerate(mutations.items()):
        if path.suffix == '.php':
            candidate = backup/f'preflight-{index}.php'
            candidate.write_text(text, encoding='utf-8')
            subprocess.run(['php','-l',str(candidate)], check=True)
    for path, text in mutations.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix+'.ui-tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(path)
    # Syntax-check every modified PHP file before loading any new PHP worker.
    for path in mutations:
        if path.suffix == '.php':
            subprocess.run(['php','-l',str(path)], check=True)
    cache = public/'system/storage/cache'
    for path in cache.rglob('*.php'):
        if 'template' in path.parts:
            path.unlink()
    settings = subprocess.check_output(['php-fpm8.3','-i'], text=True)
    if not re.search(r'^opcache.validate_timestamps => On',settings,re.M):
        subprocess.run(['systemctl','reload','php8.3-fpm'], check=True)
    print('Installed unified UI:',len(mutations),'files. Brand aliases:',len(aliases),'. Rollback:',backup)


if __name__ == '__main__':
    main()
