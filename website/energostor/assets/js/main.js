/* ЭНЕРГОСТОР — интерактив главной страницы.
   Без зависимостей: меню, мегаменю, модальное окно, форма, анимация появления. */

(function () {
  'use strict';

  var header = document.getElementById('site-header');
  var burger = document.querySelector('[data-burger]');
  var mobileMenu = document.getElementById('mobile-menu');
  var megaItem = document.querySelector('[data-mega]');
  var megaButton = megaItem ? megaItem.querySelector('.nav__link--toggle') : null;
  var megaPanel = document.getElementById('mega-menu');
  var dialog = document.getElementById('modal');
  var form = document.getElementById('lead-form');
  var formTitle = document.getElementById('modal-title');
  var formSubject = document.getElementById('form-subject');
  var statusEl = form ? form.querySelector('.form__status') : null;

  var MODAL_TEXTS = {
    kp: { title: 'Получите коммерческое предложение и сроки', subject: 'Запрос КП и сроков' },
    callback: { title: 'Получите бесплатную консультацию от менеджера', subject: 'Обратный звонок' },
    spec: { title: 'Пришлите ссылку на спецификацию — посчитаем поставку', subject: 'Спецификация' },
    default: { title: 'Получите бесплатную консультацию от менеджера', subject: 'Заявка с сайта' }
  };

  /* ---------- Шапка ---------- */

  function onScroll() {
    if (!header) return;
    header.classList.toggle('is-scrolled', window.scrollY > 8);
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ---------- Мобильное меню ---------- */

  function closeMobile() {
    if (!mobileMenu || !burger) return;
    mobileMenu.hidden = true;
    mobileMenu.classList.remove('is-open');
    burger.classList.remove('is-open');
    burger.setAttribute('aria-expanded', 'false');
    burger.setAttribute('aria-label', 'Открыть меню');
    document.body.style.overflow = '';
  }

  if (burger && mobileMenu) {
    burger.addEventListener('click', function () {
      var open = burger.classList.toggle('is-open');
      burger.setAttribute('aria-expanded', String(open));
      burger.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
      mobileMenu.classList.toggle('is-open', open);
      mobileMenu.hidden = !open;
      document.body.style.overflow = open ? 'hidden' : '';
      if (open) closeMega();
    });

    mobileMenu.addEventListener('click', function (e) {
      if (e.target.closest('a')) closeMobile();
    });

    window.addEventListener('resize', function () {
      if (window.innerWidth > 1024) closeMobile();
    });
  }

  /* ---------- Мегаменю «Направления» ---------- */

  var megaTimer = null;
  

  function openMega() {
    if (!megaPanel || !megaButton) return;
    clearTimeout(megaTimer);
    megaPanel.hidden = false;
    megaItem.classList.add('is-open');
    megaButton.setAttribute('aria-expanded', 'true');
  }

  function closeMega() {
    if (!megaPanel || !megaButton) return;
    megaPanel.hidden = true;
    megaItem.classList.remove('is-open');
    megaButton.setAttribute('aria-expanded', 'false');
  }

  if (megaItem && megaButton && megaPanel) {
    megaButton.addEventListener('click', function (e) {
      e.preventDefault();
      if (megaPanel.hidden) openMega(); else closeMega();
    });

    // Open on explicit click so hover does not immediately invert the first click.

    document.addEventListener('click', function (e) {
      if (!megaItem.contains(e.target)) closeMega();
    });

    megaPanel.addEventListener('click', function (e) {
      if (e.target.closest('a')) closeMega();
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var megaWasOpen = megaPanel && !megaPanel.hidden;
    closeMega();
    if (megaWasOpen && megaButton) megaButton.focus();
    if (mobileMenu && !mobileMenu.hidden) closeMobile();
  });

  /* ---------- Модальное окно ---------- */

  function setStatus(text, type) {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.classList.remove('is-error', 'is-success');
    if (type) statusEl.classList.add('is-' + type);
  }

  function openModal(kind) {
    if (!dialog) return;
    var data = MODAL_TEXTS[kind] || MODAL_TEXTS.default;
    if (formTitle) formTitle.textContent = data.title;
    if (formSubject) formSubject.value = data.subject;
    setStatus('');
    closeMobile();
    closeMega();
    if (typeof dialog.showModal === 'function') {
      dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    var firstField = form ? form.querySelector('input[name="name"]') : null;
    if (firstField) setTimeout(function () { firstField.focus(); }, 60);
  }

  function closeModal() {
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-modal-open]');
    if (opener) {
      e.preventDefault();
      openModal(opener.getAttribute('data-modal-open'));
      return;
    }
    if (e.target.closest('[data-modal-close]')) {
      e.preventDefault();
      closeModal();
    }
  });

  if (dialog) {
    dialog.addEventListener('click', function (e) {
      if (e.target === dialog) {
        var rect = dialog.getBoundingClientRect();
        if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) closeModal();
      }
    });
    dialog.addEventListener('close', function () { setStatus(''); });
  }

  /* ---------- Форма ---------- */

  function markInvalid(field, invalid) {
    if (!field) return;
    field.classList.toggle('is-invalid', invalid);
    field.setAttribute('aria-invalid', invalid ? 'true' : 'false');
  }

  function validate() {
    if (!form) return false;
    var phone = form.querySelector('input[name="phone"]');
    var email = form.querySelector('input[name="email"]');
    var consent = form.querySelector('input[name="consent"]');
    var ok = true;

    var digits = phone ? phone.value.replace(/\D/g, '') : '';
    var phoneBad = !/^7\d{10}$/.test(digits);
    markInvalid(phone, phoneBad);
    if (phoneBad) ok = false;

    var emailBad = email && email.value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value);
    markInvalid(email, !!emailBad);
    if (emailBad) ok = false;

    if (consent && !consent.checked) {
      ok = false;
      setStatus('Подтвердите согласие на обработку персональных данных.', 'error');
    } else if (emailBad) {
      setStatus('Проверьте адрес электронной почты.', 'error');
    } else if (!ok) {
      setStatus('Заполните телефон в формате +7 (___) ___-__-__.', 'error');
    }

    return ok;
  }

  if (form) {
    var phoneInput = form.querySelector('input[name="phone"]');

    if (phoneInput) {
      phoneInput.addEventListener('input', function () {
        var d = phoneInput.value.replace(/\D/g, '').slice(0, 11);
        if (d.length === 0) { phoneInput.value = ''; return; }
        if (d[0] === '8') d = '7' + d.slice(1);
        else if (d[0] !== '7') d = ('7' + d).slice(0, 11);
        var out = '+' + d.charAt(0);
        if (d.length > 1) out += ' (' + d.slice(1, 4);
        if (d.length >= 5) out += ') ' + d.slice(4, 7);
        if (d.length >= 8) out += '-' + d.slice(7, 9);
        if (d.length >= 10) out += '-' + d.slice(9, 11);
        phoneInput.value = out;
        markInvalid(phoneInput, false);
      });
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      setStatus('');

      if (document.body.dataset.preview === 'true') {
        setStatus('В тестовой версии отправка отключена. Позвоните +7 (812) 200-93-40 или напишите на info@energostor.ru.', 'error');
        return;
      }
      if (!validate()) return;

      var submit = form.querySelector('.form__submit');
      var data = new FormData(form);
      var label = submit ? submit.textContent : '';
      if (submit) { submit.disabled = true; submit.textContent = 'Отправляем…'; }

      fetch(form.getAttribute('action'), {
        method: 'POST',
        body: data,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (json) {
          if (!json || json.ok !== true) throw new Error('Нет подтверждения отправки');
          form.reset();
          setStatus('Заявка отправлена. Менеджер свяжется с вами в рабочее время.', 'success');
        })
        .catch(function () {
          var phone = '+7 (812) 200-93-40';
          setStatus('Не удалось отправить форму. Позвоните: ' + phone + ' или напишите на info@energostor.ru.', 'error');
        })
        .finally(function () {
          if (submit) { submit.disabled = false; submit.textContent = label; }
        });
    });
  }

  /* ---------- Появление блоков ---------- */

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var revealTargets = document.querySelectorAll('.section__head, .card, .industry, .news-card, .footer-card');

  if (!reduceMotion && 'IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });

    revealTargets.forEach(function (el, i) {
      el.classList.add('reveal');
      el.style.transitionDelay = (i % 3) * 60 + 'ms';
      observer.observe(el);
    });
  }

  /* ---------- Год в подвале ---------- */

  var year = document.querySelector('[data-year]');
  if (year) year.textContent = new Date().getFullYear();
})();
