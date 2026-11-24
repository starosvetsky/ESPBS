/* Loaded only once SMTP has been configured and tested. */
(function () {
  'use strict';
  document.addEventListener('submit', async function (event) {
    var form = event.target;
    if (!form.matches('#lead-form, .consultation-form')) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!form.reportValidity() || form.dataset.sending) return;
    var button = form.querySelector('[type="submit"]');
    var status = form.querySelector('[role="status"]');
    if (!status) {
      status = document.createElement('div');
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      form.appendChild(status);
    }
    var label = button.textContent;
    form.dataset.sending = 'true'; button.disabled = true;
    button.textContent = 'Отправляем…'; status.textContent = '';
    var abort = new AbortController();
    var timer = setTimeout(function () { abort.abort(); }, 25000);
    try {
      var response = await fetch('index.php?route=information/lead', {
        method: 'POST', body: new FormData(form), signal: abort.signal,
        headers: { 'Accept': 'application/json' }
      });
      var result = await response.json();
      if (!response.ok || result.ok !== true) throw new Error(result.message || 'Не удалось отправить заявку.');
      form.reset();
      status.textContent = 'Заявка отправлена. Свяжемся с вами в рабочее время.';
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'Ответ сервера не получен. Уточните получение заявки по телефону 8 (812) 200-93-40.' : (error.message + ' Можно написать на info@energostor.ru.');
    } finally {
      clearTimeout(timer); delete form.dataset.sending;
      button.disabled = false; button.textContent = label;
    }
  }, true);
}());
