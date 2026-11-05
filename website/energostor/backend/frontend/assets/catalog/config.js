/* Настройки каталога.
   apiBase: 'auto' — на рабочем сайте используется /energostor/api/catalog,
   а при локальном просмотре с 127.0.0.1 — напрямую сервис на порту 8766.
   Можно задать строкой, чтобы переопределить. */

window.ENERGOSTOR_CATALOG = {
  apiBase: 'auto',
  localApi: 'http://127.0.0.1:8766',
  requestEmail: 'info@energostor.ru',
  requestPhone: '+7 (812) 200-93-40',
  phoneHref: 'tel:+78122009340',
  siteRoot: '../',
};
