/* Страница «По брендам»: список брендов из метаданных каталога. */

(function () {
  'use strict';

  var util = window.CatalogUtil;
  var api = window.CatalogAPI;
  var el = util.el;

  var stateNode = document.getElementById('brand-state');
  var groups = document.getElementById('brand-groups');
  var alpha = document.getElementById('alpha');
  var queryInput = document.getElementById('brand-query');
  var form = document.getElementById('brand-form');

  var brands = [];

  function letterOf(title) {
    var first = (title || '').trim().charAt(0).toUpperCase();
    if (!first) return '#';
    if (/[А-ЯЁ]/.test(first)) return first === 'Ё' ? 'Е' : first;
    if (/[A-Z]/.test(first)) return first;
    return '#';
  }

  function countLabel(count) {
    return util.number(count) + ' ' + util.plural(count, 'товар', 'товара', 'товаров');
  }

  function render() {
    var needle = queryInput.value.trim().toLowerCase();
    var list = brands.filter(function (brand) {
      return !needle || brand.title.toLowerCase().indexOf(needle) !== -1;
    });

    groups.textContent = '';
    alpha.textContent = '';
    alpha.hidden = true;

    if (!list.length) {
      stateNode.hidden = false;
      stateNode.textContent = '';
      stateNode.appendChild(el('h2', '', 'Бренд не найден'));
      stateNode.appendChild(el('p', '', 'Попробуйте другое написание или сбросьте поиск.'));
      var reset = el('button', '', 'Показать все бренды');
      reset.type = 'button';
      reset.addEventListener('click', function () { queryInput.value = ''; render(); });
      stateNode.appendChild(reset);
      return;
    }

    stateNode.hidden = true;

    var grouped = {};
    list.forEach(function (brand) {
      var letter = letterOf(brand.title);
      (grouped[letter] = grouped[letter] || []).push(brand);
    });

    function rank(letter) {
      if (/[A-Z]/.test(letter)) return 0;
      if (/[А-ЯЁ]/.test(letter)) return 1;
      return 2;
    }
    var letters = Object.keys(grouped).sort(function (a, b) {
      var diff = rank(a) - rank(b);
      return diff !== 0 ? diff : a.localeCompare(b, 'ru');
    });

    if (letters.length > 1) {
      alpha.hidden = false;
      letters.forEach(function (letter) {
        var link = el('a', '', letter);
        link.href = '#letter-' + encodeURIComponent(letter);
        alpha.appendChild(link);
      });
    }

    letters.forEach(function (letter) {
      var heading = el('h2', 'brand-letter', letter);
      heading.id = 'letter-' + letter;
      groups.appendChild(heading);

      var grid = el('div', 'brand-grid');
      grouped[letter].forEach(function (brand) {
        var card = el('a', 'brand-card');
        card.href = '../catalog/?brand=' + encodeURIComponent(brand.slug);
        card.appendChild(el('span', 'brand-card__name', brand.title));
        card.appendChild(el('span', 'brand-card__count', countLabel(brand.count)));
        grid.appendChild(card);
      });
      groups.appendChild(grid);
    });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    render();
  });

  queryInput.addEventListener('input', util.debounce(render, 150));

  api.meta()
    .then(function (data) {
      brands = (data.brands || []).slice();
      render();
    })
    .catch(function () {
      stateNode.hidden = false;
      stateNode.textContent = '';
      stateNode.appendChild(el('h2', '', 'Бренды недоступны'));
      stateNode.appendChild(el('p', '', 'Не удалось получить список брендов. Обновите страницу позже.'));
    });

  var year = document.getElementById('year');
  if (year) year.textContent = new Date().getFullYear();
})();
