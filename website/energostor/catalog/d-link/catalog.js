(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { products: [], family: '', page: 1, size: 18, request: 0 };
  const dialog = $('product-dialog');
  const modelCount = n => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'модель' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'модели' : 'моделей'}`;
  const text = value => Array.isArray(value) ? value.map(text).join('\n') : value && typeof value === 'object' ? Object.entries(value).map(([k,v]) => k + ': ' + text(v)).join('\n') : String(value ?? '');
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function safeURL(value) {
    try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password && !/(^|\.)olnisa\.ru$/i.test(u.hostname) ? u.href : null; }
    catch { return null; }
  }
  function image(url, alt) {
    const src = safeURL(url);
    if (!src) return el('span', 'no-image', 'Фото отсутствует');
    const img = el('img'); img.src = src; img.alt = alt; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer';
    img.addEventListener('error', () => img.replaceWith(el('span', 'no-image', 'Фото недоступно')), { once: true });
    return img;
  }
  function button(label, callback, className = '') {
    const b = el('button', className, label); b.type = 'button'; b.addEventListener('click', callback); return b;
  }
  function applyFilters() { state.page = 1; render(); }
  function render() {
    const terms = $('query').value.trim().toLocaleLowerCase('ru').split(/\s+/).filter(Boolean);
    let items = state.products.filter(p => (!state.family || p.family === state.family) && (!$('with-photo').checked || p.images.length) && (!$('with-docs').checked || p.hasDocs) && terms.every(t => `${p.name} ${p.mpn} ${p.summary}`.toLocaleLowerCase('ru').includes(t)));
    items.sort((a,b) => a.mpn.localeCompare(b.mpn, 'ru', {numeric: true}) * ($('sort').value === 'desc' ? -1 : 1));
    const pages = Math.max(1, Math.ceil(items.length/state.size));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * state.size;
    $('result-count').textContent = `${modelCount(items.length)}${state.family ? ' · серия ' + state.family : ''}`;
    const grid = $('products'); grid.replaceChildren(); grid.setAttribute('aria-busy', 'false');
    for (const p of items.slice(start, start + state.size)) {
      const card = el('article', 'product');
      const top = el('div', 'product-top'); top.append(el('b', '', 'D-Link'), el('span', '', 'Серия ' + p.family));
      const photo = button('', () => openProduct(p), 'image-button'); photo.setAttribute('aria-label', 'Открыть ' + (p.mpn || p.name)); photo.append(image(p.images[0], p.mpn || p.name));
      const title = el('h2'); title.append(button(p.mpn || p.name, () => openProduct(p), 'title-button'));
      const badges = el('div', 'badges');
      if (p.hasSpecs) badges.append(el('span', 'badge', 'Характеристики'));
      if (p.hasDocs) badges.append(el('span', 'badge', 'Документация'));
      const bottom = el('div', 'product-bottom'); bottom.append(el('span', '', 'Цена по запросу'), button('Подробнее ↗', () => openProduct(p)));
      card.append(top, photo, title, el('p', 'summary', p.summary || 'Описание не сохранено'), badges, bottom); grid.append(card);
    }
    if (!items.length) grid.append(el('div', 'empty', 'Ничего не найдено. Попробуйте другую модель или сбросьте фильтры.'));
    const pagination = $('pagination'); pagination.replaceChildren();
    if (pages > 1) {
      const change = n => {state.page = n; render(); $('catalog').scrollIntoView({block:'start'});};
      const prev = button('← Назад', () => change(state.page - 1)); prev.disabled = state.page === 1;
      const next = button('Далее →', () => change(state.page + 1)); next.disabled = state.page === pages;
      pagination.append(prev, el('span', '', `${state.page} / ${pages}`), next);
    }
    for (const b of $('families').querySelectorAll('button')) { const selected = b.dataset.family === state.family; b.classList.toggle('selected', selected); b.setAttribute('aria-pressed', String(selected)); }
    const params = new URLSearchParams();
    if ($('query').value.trim()) params.set('q', $('query').value.trim());
    if (state.family) params.set('family', state.family);
    if ($('with-photo').checked) params.set('photo', '1');
    if ($('with-docs').checked) params.set('docs', '1');
    if ($('sort').value === 'desc') params.set('sort','desc');
    if (state.page > 1) params.set('page', state.page);
    history.replaceState(null, '', location.pathname + (params.size ? '?' + params : '') + location.hash);
  }
  function section(title, content) { const s = el('section', 'detail-section'); s.append(el('h3', '', title), content); return s; }
  async function openProduct(p) {
    const request = ++state.request;
    const detail = $('product-detail'); detail.replaceChildren(el('p', '', 'Загружаем карточку…'));
    if (!dialog.open) dialog.showModal();
    try {
      const response = await fetch(`data/products/${p.id}.json`); if (!response.ok) throw new Error('HTTP ' + response.status);
      const product = await response.json(); if (request !== state.request || !dialog.open) return;
      detail.replaceChildren();
      const top = el('div', 'detail-top'); const gallery = el('div');
      const hero = image(product.images[0], product.mpn || product.name); hero.classList.add('detail-image'); gallery.append(hero);
      if (product.images.length > 1) {
        const thumbs = el('div', 'gallery');
        for (const url of product.images) { const b = button('', () => { const next = image(url, product.mpn || product.name); next.classList.add('detail-image'); gallery.firstElementChild.replaceWith(next); }); b.setAttribute('aria-label', 'Показать фото'); b.append(image(url, '')); thumbs.append(b); }
        gallery.append(thumbs);
      }
      const info = el('div'); const h2 = el('h2', 'detail-title', product.mpn || product.name); h2.id = 'product-title';
      const requestLink = el('a', 'request', 'Запросить цену и сроки ↗');
      requestLink.href = 'mailto:info@energostor.ru?subject=' + encodeURIComponent('Запрос D-Link ' + (product.mpn || product.name)) + '&body=' + encodeURIComponent('Добрый день!\nПрошу рассчитать поставку D-Link ' + (product.mpn || product.name) + '\nКоличество: \nКомпания: \nТелефон: ');
      info.append(el('p', 'eyebrow', 'D-Link · серия ' + product.family), h2, el('p', 'detail-meta', 'Артикул: ' + (product.mpn || 'не указан')), el('p', '', 'Цена и наличие уточняются по запросу.'), requestLink);
      top.append(gallery, info); detail.append(top);
      if (product.description) detail.append(section('Описание', el('p', 'description', product.description)));
      if (product.attributes && Object.keys(product.attributes).length) {
        const table = el('table', 'specs'); const tbody = el('tbody');
        for (const [key, value] of Object.entries(product.attributes)) { const row = el('tr'); const th = el('th', '', key); th.scope = 'row'; row.append(th, el('td', '', text(value))); tbody.append(row); }
        table.append(tbody); detail.append(section('Характеристики', table));
      }
      if (product.documents.length) { const docs = el('ul', 'docs'); for (const doc of product.documents) { const href = safeURL(doc.url); if (!href) continue; const li = el('li'); const a = el('a', '', doc.name + ' ↗'); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; li.append(a); docs.append(li); } detail.append(section('Документация', docs)); }
      detail.append(el('p', 'snapshot', 'Сведения из сохранённого каталога. Комплектацию и актуальные параметры подтвердит менеджер.'));
    } catch { if (request === state.request) {detail.replaceChildren(el('h2', 'detail-title', p.mpn || p.name), el('p', 'error', 'Не удалось загрузить карточку. Закройте её и попробуйте ещё раз.')); detail.firstElementChild.id = 'product-title';} }
  }
  dialog.querySelector('.close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', e => { if (e.target !== dialog) return; const r = dialog.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close(); });
  $('search-form').addEventListener('submit', e => {e.preventDefault(); applyFilters();});
  let timer; $('query').addEventListener('input', () => {clearTimeout(timer); timer = setTimeout(applyFilters, 180);});
  for (const id of ['sort','with-photo','with-docs']) $(id).addEventListener('change', applyFilters);
  $('reset').addEventListener('click', () => { $('query').value = ''; $('with-photo').checked = false; $('with-docs').checked = false; $('sort').value = 'asc'; state.family = ''; applyFilters(); });
  async function init() {
    try {
      const response = await fetch('data/index.json'); if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json(); state.products = data.products;
      const params = new URLSearchParams(location.search);
      $('query').value = params.get('q') || ''; state.family = Object.hasOwn(data.families, params.get('family')) ? params.get('family') : '';
      $('with-photo').checked = params.get('photo') === '1'; $('with-docs').checked = params.get('docs') === '1'; $('sort').value = params.get('sort') === 'desc' ? 'desc' : 'asc';
      state.page = Math.max(1, parseInt(params.get('page'),10) || 1);
      const families = $('families'); families.replaceChildren();
      for (const [name, count] of [['', data.count], ...Object.entries(data.families)]) { const b = button('', () => {state.family = name; applyFilters();}, 'family'); b.dataset.family = name; b.append(el('strong','',name || 'Все серии'), el('span','',count)); families.append(b); }
      $('snapshot').textContent = `Тестовая витрина · ${modelCount(data.count)} из сохранённых товаров сервера · снимок ${new Date(data.snapshotAt).toLocaleDateString('ru-RU', {timeZone:'Asia/Krasnoyarsk'})}. Цена и сроки поставки — по запросу.`;
      render();
    } catch { $('products').setAttribute('aria-busy','false'); $('result-count').textContent = 'Каталог недоступен'; $('error').hidden = false; $('error').textContent = 'Не удалось загрузить товары. Обновите страницу. Для локального просмотра нужен HTTP-сервер.'; $('families').replaceChildren(); }
  }
  init();
})();
