/* Страница общего каталога: фильтры, поиск, пагинация, карточка товара. */

(function () {
  'use strict';

  var util = window.CatalogUtil;
  var api = window.CatalogAPI;
  var el = util.el;

  var $ = function (id) { return document.getElementById(id); };

  var node = {
    filters: $('filters'),
    tree: $('category-tree'),
    brands: $('brands-list'),
    brandsFilter: $('brands-filter'),
    searchForm: $('search-form'),
    query: $('query'),
    sort: $('sort'),
    count: $('count'),
    chips: $('chips'),
    results: $('results'),
    skeletons: $('skeletons'),
    grid: $('grid'),
    state: $('state'),
    pager: $('pager'),
    stats: $('page-stats'),
    reset: $('reset'),
    filtersToggle: $('filters-toggle'),
    dialog: $('card-dialog'),
    cardBody: $('card-body'),
    cardClose: $('card-close'),
  };

  var LIMIT = 24;
  var state = util.readState();
  var meta = null;
  var listingRequest = 0;
  var listingController = null;
  var detailRequest = 0;
  var detailController = null;
  var lastListing = null;

  /* ---------- вспомогательное ---------- */

  function titleOf(slug) {
    if (!meta || !slug) return slug;
    var found = '';
    meta.categories.forEach(function (parent) {
      if (parent.slug === slug) found = parent.title;
      parent.children.forEach(function (child) {
        if (child.slug === slug) found = child.title;
      });
    });
    return found || slug;
  }

  function parentOf(slug) {
    if (!meta) return null;
    return meta.categories.filter(function (parent) {
      return parent.slug === slug || parent.children.some(function (child) { return child.slug === slug; });
    })[0] || null;
  }

  function brandTitle(slug) {
    if (!meta) return slug;
    var hit = meta.brands.filter(function (brand) { return brand.slug === slug; })[0];
    return hit ? hit.title : slug;
  }

  function setBusy(busy) {
    node.results.setAttribute('aria-busy', busy ? 'true' : 'false');
    node.skeletons.hidden = !busy || Boolean(lastListing);
    if (busy && !lastListing) {
      node.grid.hidden = true;
      node.state.hidden = true;
    }
  }

  function showState(title, text, actionLabel, action) {
    node.state.textContent = '';
    node.state.appendChild(el('h2', '', title));
    if (text) node.state.appendChild(el('p', '', text));
    if (actionLabel && action) {
      var button = el('button', '', actionLabel);
      button.type = 'button';
      button.addEventListener('click', action);
      node.state.appendChild(button);
    }
    node.state.hidden = false;
    node.grid.hidden = true;
  }

  /* ---------- фильтры ---------- */

  function renderTree() {
    node.tree.textContent = '';
    if (!meta) return;
    meta.categories.forEach(function (parent) {
      var open = parent.slug === state.category ||
        parent.children.some(function (child) { return child.slug === state.category; });

      var row = el('div', 'cat-row');
      var main = el('button', 'cat-parent');
      main.type = 'button';
      main.setAttribute('data-category', parent.slug);
      main.setAttribute('aria-pressed', String(parent.slug === state.category));
      main.appendChild(el('span', '', parent.title));
      main.appendChild(el('span', 'count', util.number(parent.count)));
      main.addEventListener('click', function () { setCategory(parent.slug); });

      var toggle = el('button', 'cat-toggle');
      toggle.type = 'button';
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', 'Подразделы: ' + parent.title);
      toggle.textContent = open ? '−' : '+';
      toggle.addEventListener('click', function () {
        var expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        toggle.textContent = expanded ? '+' : '−';
        children.hidden = expanded;
      });

      row.appendChild(main);
      row.appendChild(toggle);
      node.tree.appendChild(row);

      var children = el('div', 'cat-children');
      children.hidden = !open;
      parent.children.forEach(function (child) {
        var button = el('button', 'cat-child');
        button.type = 'button';
        button.setAttribute('data-category', child.slug);
        button.setAttribute('aria-pressed', String(child.slug === state.category));
        button.appendChild(el('span', '', child.title));
        button.appendChild(el('span', 'count', util.number(child.count)));
        button.addEventListener('click', function () { setCategory(child.slug); });
        children.appendChild(button);
      });
      node.tree.appendChild(children);

      if (parent.slug === state.category) main.classList.add('is-active');
    });
  }

  function renderBrands() {
    node.brands.textContent = '';
    if (!meta) return;
    var needle = node.brandsFilter.value.trim().toLowerCase();
    var list = meta.brands.filter(function (brand) {
      return !needle || brand.title.toLowerCase().indexOf(needle) !== -1;
    });
    if (!list.length) {
      node.brands.appendChild(el('p', 'menu__error', 'Бренд не найден'));
      return;
    }
    list.forEach(function (brand) {
      var button = el('button', 'brand-option');
      button.type = 'button';
      button.setAttribute('aria-pressed', String(brand.slug === state.brand));
      button.appendChild(el('span', '', brand.title));
      button.appendChild(el('span', 'count', util.number(brand.count)));
      if (brand.slug === state.brand) button.classList.add('is-active');
      button.addEventListener('click', function () { setBrand(brand.slug); });
      node.brands.appendChild(button);
    });
  }

  function syncFilterState() {
    Array.prototype.forEach.call(node.tree.querySelectorAll('[data-category]'), function (button) {
      var active = button.getAttribute('data-category') === state.category;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    Array.prototype.forEach.call(node.brands.querySelectorAll('[data-brand]'), function (button) {
      button.classList.remove('is-active');
    });
  }

  /* ---------- параметры ---------- */

  function apply(next, options) {
    var opts = options || {};
    state = Object.assign({}, state, next);
    if (opts.resetPage !== false) state.page = 1;
    state.q = (state.q || '').trim();
    util.writeState(state, opts.push ? 'push' : 'replace');
    load();
    renderTree();
    renderBrands();
  }

  function setCategory(slug) {
    apply({ category: state.category === slug ? '' : slug });
  }

  function setBrand(slug) {
    apply({ brand: state.brand === slug ? '' : slug });
  }

  /* ---------- выдача ---------- */

  function load() {
    var id = ++listingRequest;
    if (listingController) listingController.abort();
    listingController = typeof AbortController === 'function' ? new AbortController() : null;
    setBusy(true);
    node.count.textContent = 'Загрузка…';

    api.products({
      q: state.q,
      brand: state.brand,
      category: state.category,
      sort: state.sort,
      page: state.page,
      limit: LIMIT,
    }, listingController ? listingController.signal : undefined)
      .then(function (data) {
        if (id !== listingRequest) return;
        lastListing = data;
        render(data);
      })
      .catch(function (error) {
        if (id !== listingRequest || (error && error.name === 'AbortError')) return;
        node.count.textContent = '';
        node.grid.hidden = true;
        node.pager.textContent = '';
        showState('Каталог недоступен', 'Не удалось получить список товаров. Проверьте соединение и попробуйте снова.', 'Повторить', function () { load(); });
      })
      .then(function () {
        if (id === listingRequest) {
          node.results.setAttribute('aria-busy', 'false');
          node.skeletons.hidden = true;
        }
      });
  }

  function render(data) {
    node.grid.textContent = '';
    node.pager.textContent = '';
    node.chips.textContent = '';

    state.page = data.page;
    var total = data.total;
    node.count.innerHTML = '';
    node.count.appendChild(el('b', '', util.productsText(total)));
    if (state.category) node.count.appendChild(document.createTextNode(' в разделе «' + titleOf(state.category) + '»'));
    if (state.q) node.count.appendChild(document.createTextNode(' по запросу «' + data.query + '»'));

    renderChips();

    if (!total) {
      node.grid.hidden = true;
      showState(
        'Ничего не найдено',
        'Попробуйте другое слово, сбросьте бренд или выберите раздел заново.',
        'Сбросить фильтры',
        resetFilters
      );
      node.results.setAttribute('aria-busy', 'false');
      node.skeletons.hidden = true;
      return;
    }

    node.state.hidden = true;
    node.grid.hidden = false;
    data.items.forEach(function (item) {
      node.grid.appendChild(card(item));
    });
    renderPager(data);
    node.results.setAttribute('aria-busy', 'false');
    node.skeletons.hidden = true;
  }

  function card(item) {
    var article = el('article', 'card');

    var media = el('button', 'card__media');
    media.type = 'button';
    media.setAttribute('aria-label', 'Открыть карточку: ' + item.name);
    var image = util.image(item.image, item.name);
    if (image) {
      media.appendChild(image);
    } else {
      media.classList.add('is-empty');
      media.appendChild(el('span', '', 'Фото нет'));
    }
    media.addEventListener('click', function () { openCard(item.id); });

    var body = el('div', 'card__body');
    if (item.brand) body.appendChild(el('p', 'card__brand', item.brand));

    var name = el('h2', 'card__name');
    var nameButton = el('button', '', item.name);
    nameButton.type = 'button';
    nameButton.addEventListener('click', function () { openCard(item.id); });
    name.appendChild(nameButton);
    body.appendChild(name);

    var metaLine = el('p', 'card__meta');
    if (item.mpn) metaLine.appendChild(el('span', '', 'Арт. ' + item.mpn));
    if (item.childTitle) metaLine.appendChild(el('span', '', item.childTitle));
    body.appendChild(metaLine);

    var badges = el('div', 'card__meta');
    if (item.hasAttrs) badges.appendChild(el('span', 'badge', 'Характеристики'));
    if (item.hasDocs) badges.appendChild(el('span', 'badge', 'Документы'));
    if (badges.childNodes.length) body.appendChild(badges);

    var foot = el('div', 'card__foot');
    foot.appendChild(el('span', '', 'Цена по запросу'));
    var more = el('button', 'card__more', 'Подробнее');
    more.type = 'button';
    more.addEventListener('click', function () { openCard(item.id); });
    foot.appendChild(more);
    body.appendChild(foot);

    article.appendChild(media);
    article.appendChild(body);
    return article;
  }

  function renderChips() {
    node.chips.textContent = '';
    function chip(label, clear) {
      var wrap = el('span', 'chip');
      wrap.appendChild(el('span', '', label));
      var button = el('button', '', '×');
      button.type = 'button';
      button.setAttribute('aria-label', 'Убрать фильтр: ' + label);
      button.addEventListener('click', clear);
      wrap.appendChild(button);
      node.chips.appendChild(wrap);
    }
    if (state.q) chip('Поиск: ' + state.q, function () { node.query.value = ''; apply({ q: '' }); });
    if (state.brand) chip('Бренд: ' + brandTitle(state.brand), function () { apply({ brand: '' }); });
    if (state.category) chip('Раздел: ' + titleOf(state.category), function () { apply({ category: '' }); });
  }

  function renderPager(data) {
    node.pager.textContent = '';
    if (data.pages <= 1) return;

    var prev = el('button', '', '← Назад');
    prev.type = 'button';
    prev.disabled = data.page <= 1;
    prev.addEventListener('click', function () { goTo(data.page - 1); });

    var next = el('button', '', 'Далее →');
    next.type = 'button';
    next.disabled = data.page >= data.pages;
    next.addEventListener('click', function () { goTo(data.page + 1); });

    node.pager.appendChild(prev);
    node.pager.appendChild(el('span', 'current', 'Страница ' + data.page + ' из ' + data.pages));
    node.pager.appendChild(next);
  }

  function goTo(page) {
    state.page = page;
    util.writeState(state, 'push');
    load();
    renderTree();
    document.getElementById('catalog').scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  function resetFilters() {
    node.query.value = '';
    node.brandsFilter.value = '';
    apply({ q: '', brand: '', category: '', sort: 'name' }, { resetPage: true });
  }

  /* ---------- карточка товара ---------- */

  function openCard(id) {
    var request = ++detailRequest;
    if (detailController) detailController.abort();
    detailController = typeof AbortController === 'function' ? new AbortController() : null;
    node.cardBody.textContent = '';
    node.cardBody.appendChild(el('p', '', 'Загружаем карточку…'));
    if (!node.dialog.open) node.dialog.showModal();

    api.product(id, detailController ? detailController.signal : undefined)
      .then(function (product) {
        if (request !== detailRequest) return;
        renderCard(product);
      })
      .catch(function (error) {
        if (request !== detailRequest || (error && error.name === 'AbortError')) return;
        node.cardBody.textContent = '';
        node.cardBody.appendChild(el('h2', 'detail__title', 'Карточка недоступна'));
        node.cardBody.appendChild(el('p', '', 'Не удалось загрузить товар. Закройте окно и попробуйте ещё раз.'));
      });
  }

  function renderCard(product) {
    node.cardBody.textContent = '';

    var title = el('h2', 'detail__title', product.name);
    title.id = 'card-title';
    title.tabIndex = -1;

    var detail = el('div', 'detail');

    var gallery = el('div', 'gallery');
    var main = el('div', 'gallery__main');
    var images = product.images || [];
    if (images.length) {
      var first = util.image(images[0], product.name);
      if (first) main.appendChild(first);
    } else {
      main.appendChild(el('span', 'gallery__empty', 'Фото не сохранено'));
    }
    gallery.appendChild(main);

    if (images.length > 1) {
      var thumbs = el('div', 'gallery__thumbs');
      images.forEach(function (url, index) {
        var button = el('button', 'gallery__thumb' + (index === 0 ? ' is-active' : ''));
        button.type = 'button';
        button.setAttribute('aria-label', 'Фото ' + (index + 1));
        var thumb = util.image(url, '');
        if (thumb) button.appendChild(thumb);
        button.addEventListener('click', function () {
          var picture = util.image(url, product.name);
          if (!picture) return;
          main.textContent = '';
          main.appendChild(picture);
          Array.prototype.forEach.call(thumbs.children, function (child) { child.classList.remove('is-active'); });
          button.classList.add('is-active');
        });
        thumbs.appendChild(button);
      });
      gallery.appendChild(thumbs);
    }

    var info = el('div', 'detail__info');
    info.appendChild(el('p', 'detail__eyebrow', [product.parentTitle, product.childTitle].filter(Boolean).join(' · ')));
    info.appendChild(title);

    var meta = el('div', 'detail__meta');
    if (product.brand) meta.appendChild(row('Бренд', product.brand));
    if (product.mpn) meta.appendChild(row('Артикул', product.mpn));
    if (product.childTitle) meta.appendChild(row('Раздел', product.childTitle));
    info.appendChild(meta);

    var actions = el('div', 'detail__actions');
    var request = el('a', '', 'Запросить цену и сроки');
    request.href = util.mailtoRequest('Запрос: ' + (product.mpn || product.name), [
      'Товар: ' + product.name,
      'Артикул: ' + (product.mpn || '—'),
      'Бренд: ' + (product.brand || '—'),
    ]);
    actions.appendChild(request);
    info.appendChild(actions);
    info.appendChild(el('p', 'detail__note', 'Цена по запросу: стоимость и наличие подтверждает менеджер. Данные карточки взяты из сохранённого каталога.'));

    detail.appendChild(gallery);
    detail.appendChild(info);
    node.cardBody.appendChild(detail);
    // Фокус на заголовке: диалог открывается для чтения, а не для кнопки «×».
    title.focus({ preventScroll: true });

    if (product.description) {
      node.cardBody.appendChild(section('Описание', el('p', 'description', product.description)));
    }

    if (product.attributes && product.attributes.length) {
      var table = el('table', 'specs');
      var tbody = el('tbody');
      product.attributes.forEach(function (attribute) {
        var tr = el('tr');
        var th = el('th', '', attribute.label);
        th.scope = 'row';
        tr.appendChild(th);
        tr.appendChild(el('td', '', attribute.value));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      node.cardBody.appendChild(section('Характеристики', table));
    }

    if (product.documents && product.documents.length) {
      var list = el('ul', 'docs');
      product.documents.forEach(function (doc) {
        var href = util.safeUrl(doc.url);
        if (!href) return;
        var item = el('li');
        var link = el('a', '', doc.name);
        link.href = href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        item.appendChild(link);
        list.appendChild(item);
      });
      if (list.childNodes.length) node.cardBody.appendChild(section('Документация', list));
    }
  }

  function row(label, value) {
    var line = el('p');
    line.appendChild(el('span', '', label + ': '));
    line.appendChild(el('b', '', value));
    return line;
  }

  function section(title, content) {
    var block = el('section', 'detail__section');
    block.appendChild(el('h3', '', title));
    block.appendChild(content);
    return block;
  }

  /* ---------- запуск ---------- */

  function renderStats(data) {
    if (!data || !data.stats) return;
    var stats = data.stats;
    node.stats.textContent = '';
    node.stats.appendChild(stat(util.productsText(stats.products), 'в каталоге'));
    node.stats.appendChild(stat(util.number(stats.brands), 'брендов'));
    node.stats.appendChild(stat(util.number(stats.categories), 'разделов'));
    if (stats.last_collected) {
      var date = new Date(stats.last_collected);
      if (!isNaN(date)) node.stats.appendChild(stat(date.toLocaleDateString('ru-RU', { timeZone: 'Asia/Krasnoyarsk' }), 'последний снимок'));
    }
    node.stats.hidden = false;
  }

  function stat(value, label) {
    var wrap = el('span');
    wrap.appendChild(el('b', '', value));
    wrap.appendChild(document.createTextNode(' ' + label));
    return wrap;
  }

  function boot() {
    node.query.value = state.q;
    node.sort.value = ['name', 'brand', 'new'].indexOf(state.sort) !== -1 ? state.sort : 'name';

    api.meta()
      .then(function (data) {
        meta = data;
        renderTree();
        renderBrands();
        renderStats(data);
      })
      .catch(function () {
        node.tree.textContent = '';
        node.brands.textContent = '';
        node.tree.appendChild(el('p', 'menu__error', 'Разделы недоступны.'));
        node.brands.appendChild(el('p', 'menu__error', 'Бренды недоступны.'));
      });

    load();

    node.searchForm.addEventListener('submit', function (event) {
      event.preventDefault();
      apply({ q: node.query.value }, { push: true });
    });

    node.query.addEventListener('input', util.debounce(function () {
      if (node.query.value.trim() === state.q) return;
      apply({ q: node.query.value });
    }, 320));

    node.sort.addEventListener('change', function () {
      apply({ sort: node.sort.value });
    });

    node.brandsFilter.addEventListener('input', util.debounce(renderBrands, 120));

    if (node.filtersToggle) {
      var collapsedByDefault = window.matchMedia('(max-width: 860px)').matches;
      if (collapsedByDefault) {
        node.filters.classList.add('is-collapsed');
        node.filtersToggle.setAttribute('aria-expanded', 'false');
      }
      node.filtersToggle.addEventListener('click', function () {
        var collapsed = node.filters.classList.toggle('is-collapsed');
        node.filtersToggle.setAttribute('aria-expanded', String(!collapsed));
        node.filtersToggle.querySelector('.filters-toggle__chevron').textContent = collapsed ? '▾' : '▴';
      });
    }

    node.reset.addEventListener('click', resetFilters);

    node.cardClose.addEventListener('click', function () { node.dialog.close(); });
    node.dialog.addEventListener('click', function (event) {
      if (event.target !== node.dialog) return;
      var rect = node.dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right ||
          event.clientY < rect.top || event.clientY > rect.bottom) {
        node.dialog.close();
      }
    });
    node.dialog.addEventListener('close', function () {
      detailRequest += 1;
      if (detailController) detailController.abort();
    });

    window.addEventListener('popstate', function () {
      state = util.readState();
      node.query.value = state.q;
      node.sort.value = ['name', 'brand', 'new'].indexOf(state.sort) !== -1 ? state.sort : 'name';
      renderTree();
      renderBrands();
      load();
    });

    var year = document.getElementById('year');
    if (year) year.textContent = new Date().getFullYear();
  }

  boot();
})();
