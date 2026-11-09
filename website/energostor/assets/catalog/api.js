/* Общий клиент каталога: адреса API, запросы, состояние в URL, утилиты DOM. */

(function (global) {
  'use strict';

  var config = global.ENERGOSTOR_CATALOG || {};
  var email = config.requestEmail || 'info@energostor.ru';
  var phone = config.requestPhone || '+7 (812) 200-93-40';

  function base() {
    var configured = config.apiBase;
    if (configured && configured !== 'auto') return String(configured).replace(/\/+$/, '');
    var local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
    var underSite = location.pathname.indexOf('/energostor/') === 0;
    if (local && !underSite) return (config.localApi || 'http://127.0.0.1:8766').replace(/\/+$/, '');
    return underSite ? '/energostor/api/catalog' : '/api/catalog';
  }

  function qs(params) {
    var search = new URLSearchParams();
    Object.keys(params || {}).forEach(function (key) {
      var value = params[key];
      if (value === undefined || value === null || value === '') return;
      search.set(key, String(value));
    });
    var text = search.toString();
    return text ? '?' + text : '';
  }

  function fetchJSON(path, params, signal) {
    var url = base() + path + qs(params);
    return fetch(url, {
      signal: signal,
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    }).then(function (response) {
      if (!response.ok) {
        var error = new Error('HTTP ' + response.status);
        error.status = response.status;
        throw error;
      }
      return response.json();
    });
  }

  var metaCache = null;
  var metaPromise = null;

  var api = {
    base: base,
    fetchJSON: fetchJSON,

    meta: function (signal) {
      if (metaCache) return Promise.resolve(metaCache);
      if (metaPromise) return metaPromise;
      metaPromise = fetchJSON('/api/meta', null, signal)
        .then(function (data) {
          metaCache = data;
          metaPromise = null;
          return data;
        })
        .catch(function (error) {
          metaPromise = null;
          throw error;
        });
      return metaPromise;
    },

    products: function (params, signal) {
      return fetchJSON('/api/products', params, signal);
    },

    product: function (id, signal) {
      return fetchJSON('/api/products/' + encodeURIComponent(id), null, signal);
    },
  };

  /* ---------- утилиты ---------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function safeUrl(value) {
    if (typeof value !== 'string') return null;
    try {
      var url = new URL(value, location.href);
      if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
      if (url.username || url.password) return null;
      return url.href;
    } catch (error) {
      return null;
    }
  }

  function number(value) {
    return String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  }

  function plural(count, one, few, many) {
    var n = Math.abs(count) % 100;
    var n1 = n % 10;
    if (n > 10 && n < 20) return many;
    if (n1 > 1 && n1 < 5) return few;
    if (n1 === 1) return one;
    return many;
  }

  function productsText(count) {
    return number(count) + ' ' + plural(count, 'товар', 'товара', 'товаров');
  }

  function debounce(fn, delay) {
    var timer = null;
    return function () {
      var args = arguments;
      var self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, delay);
    };
  }

  function mailtoRequest(subject, lines) {
    var body = ['Добрый день!', '', subject, '']
      .concat(lines || [])
      .concat(['', 'Компания:', 'Контактное лицо:', 'Телефон:'])
      .join('\n');
    return 'mailto:' + email + '?subject=' + encodeURIComponent(subject) +
      '&body=' + encodeURIComponent(body);
  }

  /* ---------- состояние в адресе ---------- */

  function readState() {
    var params = new URLSearchParams(location.search);
    return {
      q: params.get('q') || '',
      brand: params.get('brand') || '',
      category: params.get('category') || '',
      sort: params.get('sort') || 'name',
      page: Math.max(1, parseInt(params.get('page'), 10) || 1),
    };
  }

  function writeState(state, mode) {
    var params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.brand) params.set('brand', state.brand);
    if (state.category) params.set('category', state.category);
    if (state.sort && state.sort !== 'name') params.set('sort', state.sort);
    if (state.page && state.page > 1) params.set('page', state.page);
    var url = location.pathname + (params.toString() ? '?' + params : '');
    if (mode === 'push') history.pushState(null, '', url);
    else history.replaceState(null, '', url);
  }

  global.CatalogAPI = api;
  global.CatalogUtil = {
    el: el,
    safeUrl: safeUrl,
    number: number,
    plural: plural,
    productsText: productsText,
    debounce: debounce,
    mailtoRequest: mailtoRequest,
    readState: readState,
    writeState: writeState,
    image: function (url, alt) {
      var src = safeUrl(url);
      if (!src) return null;
      var img = el('img');
      img.src = src;
      img.alt = alt || '';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      img.decoding = 'async';
      img.addEventListener('error', function () { img.remove(); }, { once: true });
      return img;
    },
  };
})(window);
