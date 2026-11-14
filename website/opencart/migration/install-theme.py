"""Install the Energostor storefront on the isolated OpenCart release."""
import html
import json
from pathlib import Path
import re
import shutil
import sys


root = Path(sys.argv[1]).resolve()
source = Path(sys.argv[2]).resolve()
theme = root / 'energostor-theme'
templates = root / 'catalog/view/template'
build = root.parent / 'build'
migration = Path(__file__).parent


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def read(path):
    return path.read_text(encoding='utf-8')


def patch(path, old, new):
    text = read(path)
    if new in text:
        return
    if text.count(old) != 1:
        raise ValueError(f'Expected one match in {path}: {old!r}')
    write(path, text.replace(old, new))


def markup(text):
    text = re.sub(r'https://(?:www\.)?energostor\.ru/', '', text)
    text = re.sub(r'(?<=["\'])\.\./assets/', 'assets/', text)
    text = re.sub(r'(?<=["\'])assets/(?=(?:css|img|js|fonts|catalog)/)', 'energostor-theme/assets/', text)
    text = text.replace('href="catalog/"', 'href="catalog"').replace('href="vendors/"','href="vendors"').replace('href="brands/"','href="brands"')
    text = text.replace('href="members/login"', 'href="contacts"')
    text = text.replace('data-base="../"', 'data-base=""')
    text = text.replace('action="send.php"', 'action="mailto:info@energostor.ru"')
    text = re.sub(r'<p class="form__note">.*?</p>',
                  '<p class="form__note">Заявка откроется в вашем почтовом приложении.</p>', text, flags=re.S)
    return text


shutil.copytree(source/'assets', theme/'assets', dirs_exist_ok=True)
release = json.loads(read(build/'routes.json'))
paths = {s['slug']: s['url'].lstrip('/') for s in release['sections']}
groups = []
for section in release['sections']:
    if section['parent'] is None:
        groups.append({**section, 'children': [child for child in release['sections'] if child['parent']==section['slug']]})
write(theme/'catalog-data.js', 'const EnergostorRoutes = '+json.dumps(paths, ensure_ascii=False)+';\n'
      +'CatalogAPI.meta = () => Promise.resolve({categories: '+json.dumps(groups, ensure_ascii=False)+'});\n')
nav = theme/'assets/js/navigation.js'
patch(nav, "const url = path => base + path;", r"""const url = path => {
    const prefix = 'catalog/?category=';
    if (path.startsWith(prefix)) {
      return EnergostorRoutes[decodeURIComponent(path.slice(prefix.length))] || 'catalog';
    }
    return path.replace(/^assets\//, 'energostor-theme/assets/').replace(/^catalog\/$/, 'catalog');
  };""")

main = theme/'assets/js/main.js'
js = read(main)
start = js.index("      if (document.body.dataset.preview === 'true')")
end = js.index('\n    });', start)
js = js[:start]+"""      if (!validate()) return;
      var data = new FormData(form);
      var subject = String(data.get('subject') || 'Запрос в Энергостор');
      var fields = [['name','Имя'],['company','Компания'],['phone','Телефон'],['email','Email'],['message','Сообщение']];
      var message = fields.map(function (field) {
        return field[1] + ': ' + (data.get(field[0]) || '');
      }).join('\\n');
      window.location.href = 'mailto:info@energostor.ru?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(message);
      setStatus('Откроется почтовое приложение с заполненной заявкой.', 'success');"""+js[end:]
write(main,js)

home = markup(read(source/'index.html'))
home = re.sub(r'<meta name="robots"[^>]*>','',home)
home = re.sub(r'<link[^>]+rel="canonical"[^>]*>','',home)
home = home.replace('</head>', '<base href="{{ energostor_base }}"><link rel="canonical" href="https://energostor.ru/"></head>')
home = home.replace('<script src="energostor-theme/assets/js/navigation.js', '<script src="energostor-theme/catalog-data.js" defer></script>\n<script src="energostor-theme/assets/js/navigation.js')
home = home.replace('href="./"', 'href="{{ energostor_base }}"').replace(' data-preview="true"','')
write(templates/'common/home.twig',home)
patch(root/'catalog/controller/common/home.php', "$this->response->setOutput($this->load->view('common/home', $data));",
      "$data['energostor_base'] = HTTP_SERVER;\n\t\t$this->response->setOutput($this->load->view('common/home', $data));")

site_header = re.search(r'<header class="site-header".*?</header>',home,re.S).group()
site_footer = re.search(r'<footer class="site-footer".*?</footer>',home,re.S).group()
dialog = re.search(r'<dialog class="modal".*?</dialog>',home,re.S).group()
scripts = '\n'.join(re.findall(r'<script src="energostor-theme/[^"]+" defer></script>',home))
styles = '\n'.join(re.findall(r'<link rel="stylesheet" href="energostor-theme/[^"]+">',home))
header = read(templates/'common/header.twig')
header = re.split(r'<body(?:\s|>)', header, maxsplit=1)[0].replace('lang="{{ lang }}"','lang="ru"')
header = header.replace('<title>{{ title }}</title>', '<title>{{ title|e }}</title>')
header = header.replace('content="{{ description }}"', 'content="{{ description|e(\'html_attr\') }}"', 1)
if 'energostor_canonical' not in header:
    header = header.replace('  {% for link in links %}', '  {% if energostor_canonical %}<link rel="canonical" href="{{ energostor_canonical }}">{% endif %}\n  {% if energostor_noindex %}<meta name="robots" content="noindex,follow">{% endif %}\n  {% for link in links %}')
header = header.replace('<link href="energostor-theme/native.css?v=medeo16" rel="stylesheet"/>','')
if 'energostor-theme/release.css' not in header:
    header = header.replace('</head>',styles+'\n<link rel="stylesheet" href="energostor-theme/release.css?v=1">\n</head>')
header += '<body class="energostor-release"><div id="container"><div id="alert"></div>\n'+site_header.replace('{{ energostor_base }}','{{ base }}')+'\n<main id="main">\n'
write(templates/'common/header.twig',header)
patch(root/'catalog/controller/common/header.php', "$data['links'] = $this->document->getLinks();",
      """$seo = energostorSeo($this->request->get);
        $data['energostor_canonical'] = $seo['canonical'];
        $data['energostor_noindex'] = $seo['noindex'];
        $data['links'] = array_filter($this->document->getLinks(), static fn(array $link): bool => $link['rel'] !== 'canonical');""")
write(templates/'common/footer.twig','</main>\n'+site_footer+'\n'+dialog+'\n</div>\n'+scripts+'\n<script src="{{ bootstrap }}"></script>\n</body></html>\n')

brand_controller = root/'catalog/controller/product/manufacturer.php'
patch(brand_controller, "$this->document->setTitle($this->language->get('heading_title'));",
      "$this->document->setTitle('Бренды оборудования — Энергостор');\n\t\t$this->document->setDescription('Производители в каталоге Энергостора. Выберите бренд, чтобы посмотреть оборудование и комплектующие.');")
patch(brand_controller, "$this->document->setTitle($manufacturer_info['name']);",
      "$this->document->setTitle($manufacturer_info['name'] . ' — каталог Энергостора');\n\t\t\t$this->document->setDescription($manufacturer_info['name'] . ': оборудование и комплектующие. Подбор по артикулу и спецификации.');")

write(templates/'information/catalog.twig', """{{ header }}
<section class="container release-section">
  <h1>Каталог оборудования</h1>
  <form class="release-search" action="index.php" method="get">
    <input type="hidden" name="route" value="product/search">
    <input type="search" name="search" aria-label="Поиск по каталогу" placeholder="Название, артикул или бренд" required>
    <button class="btn btn-primary">Найти</button>
  </form>
  <div class="release-directory">
  {% for section in sections %}
    <a href="{{ section.url|trim('/') }}">
      <img src="energostor-theme/assets/img/menu-categories/{{ section.slug }}.webp" alt="" width="110" height="84">
      <span>{{ section.title }}</span>
    </a>
  {% endfor %}
  </div>
</section>
{{ footer }}
""")
vendors = markup(read(source/'vendors/index.html'))
vendor_content = re.search(r'<main[^>]*>(.*?)</main>',vendors,re.S).group(1)
vendor_assets = theme/'vendors'
vendor_assets.mkdir(exist_ok=True)
shutil.copytree(source/'vendors/logos', vendor_assets/'logos', dirs_exist_ok=True)
for filename in ('data.json','vendors.css'):
    shutil.copy2(source/'vendors'/filename, vendor_assets/filename)
vendor_js = read(source/'vendors/vendors.js').replace("fetch('data.json')", "fetch('energostor-theme/vendors/data.json')").replace("img.src = vendor.logo", "img.src = 'energostor-theme/vendors/' + vendor.logo")
write(vendor_assets/'vendors.js',vendor_js)
write(templates/'information/vendors.twig', '{{ header }}\n<div class="vendors-main">'+vendor_content+'</div>\n<script src="energostor-theme/vendors/vendors.js" defer></script>\n{{ footer }}\n')
vendor_style = re.findall(r'<style[^>]*>(.*?)</style>',vendors,re.S)

write(templates/'product/thumb.twig', """<article class="release-card">
  {% if image_url %}
    <a href="{{ href }}"><img src="{{ image_url|e('html_attr') }}" alt="{{ name|e('html_attr') }}" loading="lazy" referrerpolicy="no-referrer"></a>
  {% endif %}
  <h2><a href="{{ href }}">{{ name|e }}</a></h2>
  {% if description %}<p>{{ description|e }}</p>{% endif %}
  <a class="release-more" href="{{ href }}">Подробнее <span aria-hidden="true">↗</span></a>
</article>
""")
patch(root/'catalog/controller/product/thumb.php', "return $this->load->view('product/thumb', $data);",
      """$data['image_url'] = energostorRelease()['media'][$data['product_id']]['images'][0] ?? '';
        return $this->load->view('product/thumb', $data);""")
patch(root/'catalog/controller/product/product.php', "$data['heading_title'] = $product_info['name'];",
      """$data['heading_title'] = $product_info['name'];
            $data['release_media'] = energostorRelease()['media'][$product_id] ?? [];
            $data['quote_href'] = 'mailto:info@energostor.ru?subject=' . rawurlencode('Запрос КП: ' . html_entity_decode($product_info['name'], ENT_QUOTES, 'UTF-8')) . '&body=' . rawurlencode('Артикул: ' . $product_info['model'] . "\\n" . energostorSeo($this->request->get)['canonical']);""")
write(templates/'product/product.twig', """{{ header }}
<section class="container release-section release-product">
  <nav class="release-crumbs"><a href="{{ home|default('./') }}">Главная</a> / <a href="catalog">Каталог</a></nav>
  <h1>{{ heading_title|e }}</h1>
  <div class="release-detail{% if release_media.images %} has-gallery{% endif %}">
    {% if release_media.images %}
      <div class="release-gallery">
        {% for image in release_media.images %}
          <a href="{{ image|e('html_attr') }}"><img src="{{ image|e('html_attr') }}" alt="{{ heading_title|e('html_attr') }}" loading="lazy" referrerpolicy="no-referrer"></a>
        {% endfor %}
      </div>
    {% endif %}
    <div>
      {% if manufacturer %}<p><a href="{{ manufacturers }}">{{ manufacturer|e }}</a></p>{% endif %}
      {% if model %}<p>Артикул <code>{{ model|e }}</code></p>{% endif %}
      <a class="btn btn-primary" href="{{ quote_href|e('html_attr') }}">Запросить КП</a>
      {% if description %}<div class="release-description">{{ description }}</div>{% endif %}
      {% if attribute_groups %}
        <h2>Характеристики</h2>
        <table class="table"><tbody>
        {% for group in attribute_groups %}{% for attribute in group.attribute %}
          <tr><th scope="row">{{ attribute.name|e }}</th><td>{{ attribute.text|e }}</td></tr>
        {% endfor %}{% endfor %}
        </tbody></table>
      {% endif %}
      {% if release_media.documents %}
        <h2>Документы</h2>
        <ul>{% for document in release_media.documents %}
          <li><a href="{{ document|e('html_attr') }}" rel="nofollow noopener" target="_blank">Документ {{ loop.index }} ↗</a></li>
        {% endfor %}</ul>
      {% endif %}
    </div>
  </div>
</section>
{{ footer }}
""")

for name in ('category','manufacturer_info','search'):
    file = templates/f'product/{name}.twig'
    text = read(file)
    text = re.sub(r'(?m)^.*id="compare-total".*\n', '', text)
    if "{% if 'price' not in sorts.value %}" not in text:
        text = re.sub(r"({% for sorts in sorts %})(.*?)(\{% endfor %\})",
                      r"\1{% if 'price' not in sorts.value %}\2{% endif %}\3", text, flags=re.S)
    write(file,text)

write(theme/'release.css', """@import url("vendors/vendors.css");
body.energostor-release { background: #f5f7fa; color: #18232e; }
.energostor-release main > .container, .release-section { padding-block: 32px 60px; }
.release-search { display: flex; gap: 8px; max-width: 700px; margin: 22px 0 30px; }
.release-search input { min-width: 0; flex: 1; padding: 12px; border: 1px solid #b9c8d8; }
.release-directory { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
.release-directory a, .release-card { background: #fff; border: 1px solid #dbe3ec; border-radius: 8px; padding: 18px; }
.release-directory a { display: grid; gap: 12px; justify-items: start; align-content: start; }
.release-directory img { object-fit: contain; }
.release-card { height: 100%; display: flex; flex-direction: column; gap: 10px; }
.release-card h2 { font-size: 19px; line-height: 1.3; overflow-wrap: anywhere; }
.release-card img { width: 100%; height: 120px; object-fit: contain; }
.release-card p { color: #546475; font-size: 14px; overflow-wrap: anywhere; }
.release-more { margin-top: auto; color: #0b54a0; }
.release-crumbs { margin-bottom: 18px; }
.release-detail { margin-top: 22px; }
.release-detail.has-gallery { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(0, 2fr); gap: 28px; }
.release-gallery { display: grid; align-content: start; gap: 14px; }
.release-gallery img { width: 100%; max-height: 360px; object-fit: contain; background: white; }
.release-description { margin: 24px 0; overflow-wrap: anywhere; }
.energostor-release #information-information img { max-width: 100%; height: auto; }
.energostor-release #information-information #content > div { margin-block: 12px; }
.energostor-release #information-information table { display: block; overflow-x: auto; }
@media (max-width: 680px) { .release-detail.has-gallery { grid-template-columns: 1fr; } }
"""+'\n'.join(vendor_style))

shutil.copy2(migration/'catalog.php', root/'catalog/controller/information/catalog.php')
shutil.copy2(migration/'catalog-routing.php', root.parent/'catalog-routing.php')
patch(root/'index.php', "// Framework\n", "require_once dirname(__DIR__) . '/catalog-routing.php';\nenergostorRequest();\n\n// Framework\n")
patch(root/'catalog/controller/startup/setting.php', "$this->registry->set('url', new \\Opencart\\System\\Library\\Url($this->config->get('config_url')));",
      "$url = new \\Opencart\\System\\Library\\Url($this->config->get('config_url'));\n\t\t$url->addRewrite(new \\EnergostorLinks());\n\t\t$this->registry->set('url', $url);")
