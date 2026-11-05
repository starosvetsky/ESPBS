/* Меню каталога: строит двухуровневый список разделов из /api/meta.
   Подключается на любой странице сайта:

     <script src="/energostor/assets/catalog/config.js"></script>
     <script src="/energostor/assets/catalog/api.js"></script>
     <script src="/energostor/assets/catalog/menu.js"></script>
     ...
     <div data-catalog-menu></div>

   Или вручную: CatalogMenu.mount(element).
   Требует config.js и api.js. */

(function (global) {
  'use strict';

  var util = global.CatalogUtil;

  function paths() {
    var here = location.pathname;
    var inCatalog = here.indexOf('/catalog/') !== -1;
    var inBrands = here.indexOf('/brands/') !== -1;
    if (inCatalog || inBrands) {
      return { catalog: '../catalog/', brands: '../brands/' };
    }
    return { catalog: 'catalog/', brands: 'brands/' };
  }

  function categoryUrl(slug) {
    var base = paths().catalog + (slug ? '?category=' + encodeURIComponent(slug) : '');
    return base;
  }

  function group(parent) {
    var block = util.el('div', 'menu__group');
    var link = util.el('a', 'menu__parent');
    link.href = categoryUrl(parent.slug);
    link.appendChild(util.el('span', '', parent.title));
    link.appendChild(util.el('span', 'menu__count', util.number(parent.count)));
    block.appendChild(link);

    var children = util.el('div', 'menu__children');
    parent.children.forEach(function (child) {
      var item = util.el('a', 'menu__child');
      item.href = categoryUrl(child.slug);
      item.appendChild(util.el('span', '', child.title));
      item.appendChild(util.el('span', 'menu__count', util.number(child.count)));
      children.appendChild(item);
    });
    block.appendChild(children);
    return block;
  }

  function build(panel, data) {
    panel.textContent = '';
    var columns = util.el('div', 'menu__columns');
    data.categories.forEach(function (parent) {
      if (parent.children.length) columns.appendChild(group(parent));
    });
    panel.appendChild(columns);

    var footer = util.el('div', 'menu__footer');
    var all = util.el('a', '', 'Все товары каталога');
    all.href = paths().catalog;
    var brands = util.el('a', '', 'По брендам');
    brands.href = paths().brands;
    footer.appendChild(all);
    footer.appendChild(brands);
    panel.appendChild(footer);
  }

  function mount(element) {
    if (!element || element.getAttribute('data-menu-ready') === '1') return;
    element.setAttribute('data-menu-ready', '1');
    element.classList.add('menu');
    element.textContent = '';

    var id = 'catalog-menu-panel';
    var toggle = util.el('button', 'menu__toggle');
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-controls', id);
    toggle.appendChild(document.createTextNode('Каталог'));

    var chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    chevron.setAttribute('class', 'menu__chevron');
    chevron.setAttribute('width', '10');
    chevron.setAttribute('height', '10');
    chevron.setAttribute('viewBox', '0 0 10 10');
    chevron.setAttribute('aria-hidden', 'true');
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M1 3.5 5 7l4-3.5');
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', 'currentColor');
    path.setAttribute('stroke-width', '1.4');
    chevron.appendChild(path);
    toggle.appendChild(chevron);

    var panel = util.el('div', 'menu__panel');
    panel.id = id;
    panel.hidden = true;
    panel.appendChild(util.el('p', 'menu__loading', 'Загружаем разделы…'));

    element.appendChild(toggle);
    element.appendChild(panel);

    function close() {
      panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
    }

    function open() {
      panel.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
      if (!panel.getAttribute('data-loaded')) {
        global.CatalogAPI.meta()
          .then(function (data) {
            panel.setAttribute('data-loaded', '1');
            build(panel, data);
          })
          .catch(function () {
            panel.textContent = '';
            var error = util.el('p', 'menu__error', 'Разделы временно недоступны.');
            panel.appendChild(error);
          });
      }
    }

    toggle.addEventListener('click', function () {
      if (panel.hidden) open(); else close();
    });

    toggle.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        open();
        var first = panel.querySelector('a');
        if (first) first.focus();
      }
    });

    document.addEventListener('click', function (event) {
      if (!element.contains(event.target)) close();
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) {
        close();
        toggle.focus();
      }
    });
  }

  function autoMount() {
    var nodes = document.querySelectorAll('[data-catalog-menu]');
    Array.prototype.forEach.call(nodes, mount);
  }

  global.CatalogMenu = { mount: mount, refresh: autoMount };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
  } else {
    autoMount();
  }
})(window);
