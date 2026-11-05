(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { items: [], letter: '', page: 1, size: 36 };
  const collator = new Intl.Collator('ru', { numeric: true, sensitivity: 'base' });
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase('ru').replace(/ё/g, 'е');
  function initial(name) {
    const first = name.replace(/^[^\p{L}\p{N}]+/u, '').charAt(0).toLocaleUpperCase('ru');
    return /\d/.test(first) ? '0–9' : first;
  }
  function node(tag, cls, value) {
    const el = document.createElement(tag); if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  function button(label, callback) {const b = node('button', '', label); b.type = 'button'; b.addEventListener('click', callback); return b;}
  function filter() {state.page = 1; render();}
  function render() {
    const query = normalize($('vendor-query').value.trim());
    const items = state.items.filter(v => (!state.letter || initial(v.name) === state.letter) && normalize(v.name).includes(query));
    const pages = Math.max(1, Math.ceil(items.length / state.size)); state.page = Math.min(state.page, pages);
    const first = (state.page - 1) * state.size;
    $('vendor-count').textContent = `Найдено: ${items.length}${items.length ? ` · ${first + 1}–${Math.min(first + state.size, items.length)}` : ''}`;
    const grid = $('vendor-grid'); grid.replaceChildren(); grid.setAttribute('aria-busy', 'false');
    for (const vendor of items.slice(first, first + state.size)) {
      const card = node('article', 'vendor-card');
      const logo = node('div', 'vendor-logo');
      const fallback = () => logo.replaceChildren(node('span', 'vendor-monogram', vendor.name.slice(0, 2).toLocaleUpperCase('ru')));
      if (vendor.logo && /^logos\/[a-f0-9]{20}\.(png|jpe?g|svg|webp|gif)$/.test(vendor.logo)) {
        const img = node('img'); img.src = vendor.logo; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; img.addEventListener('error', fallback, {once: true}); logo.append(img);
      } else fallback();
      const contact = node('a', '', 'Запросить поставку ↗');
      contact.href = 'mailto:info@energostor.ru?subject=' + encodeURIComponent('Запрос оборудования ' + vendor.name) + '&body=' + encodeURIComponent('Добрый день!\nИнтересует оборудование ' + vendor.name + '.\nМодель: \nКоличество: \nКонтактный телефон: ');
      contact.setAttribute('aria-label', 'Запросить поставку ' + vendor.name);
      card.append(logo, node('h2', '', vendor.name), contact); grid.append(card);
    }
    if (!items.length) grid.append(node('p', 'vendor-empty', 'Ничего не найдено. Измените запрос или сбросьте фильтры.'));
    const pagination = $('vendor-pages'); pagination.replaceChildren();
    if (pages > 1) {
      const move = delta => {state.page += delta; render(); $('vendor-search').scrollIntoView({block: 'start'});};
      const prev = button('← Назад', () => move(-1)); prev.disabled = state.page === 1;
      const next = button('Далее →', () => move(1)); next.disabled = state.page === pages;
      pagination.append(prev, node('span', '', `Страница ${state.page} из ${pages}`), next);
    }
    for (const b of $('vendor-alphabet').querySelectorAll('button')) {const selected = b.dataset.letter === state.letter; b.classList.toggle('selected', selected); b.setAttribute('aria-pressed', String(selected));}
    const params = new URLSearchParams();
    if ($('vendor-query').value.trim()) params.set('q', $('vendor-query').value.trim());
    if (state.letter) params.set('letter', state.letter);
    if (state.page > 1) params.set('page', state.page);
    history.replaceState(null, '', location.pathname + (params.size ? '?' + params : ''));
  }
  $('vendor-search').addEventListener('submit', e => {e.preventDefault(); filter();});
  let timer;
  $('vendor-query').addEventListener('input', () => {clearTimeout(timer); timer = setTimeout(filter, 150);});
  $('vendor-reset').addEventListener('click', () => {clearTimeout(timer); $('vendor-query').value = ''; state.letter = ''; filter();});
  async function init() {
    try {
      const response = await fetch('data.json'); if (!response.ok) throw new Error('Load failed');
      const data = await response.json(); state.items = data.vendors.sort((a, b) => collator.compare(a.name, b.name));
      const letters = [...new Set(state.items.map(v => initial(v.name)))].sort(collator.compare);
      const params = new URLSearchParams(location.search); $('vendor-query').value = params.get('q') || '';
      state.letter = letters.includes(params.get('letter')) ? params.get('letter') : '';
      state.page = Math.max(1, parseInt(params.get('page'), 10) || 1);
      $('vendor-total').textContent = `${state.items.length} вендоров`;
      for (const letter of ['', ...letters]) {const b = button(letter || 'Все', () => {state.letter = letter; filter();}); b.dataset.letter = letter; $('vendor-alphabet').append(b);}
      render();
    } catch {
      $('vendor-count').textContent = 'Не удалось загрузить список'; $('vendor-grid').setAttribute('aria-busy', 'false');
      $('vendor-error').hidden = false; $('vendor-error').textContent = 'Обновите страницу, чтобы загрузить вендоров. Или напишите нам на info@energostor.ru.';
    }
  }
  init();
})();
