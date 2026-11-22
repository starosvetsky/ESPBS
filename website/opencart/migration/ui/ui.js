(() => {
  'use strict';
  const announce = document.createElement('span');
  announce.className = 'ui-sr'; announce.setAttribute('role', 'status');
  document.body.append(announce);
  // A base URL is required by OpenCart; fragment links must stay on this page.
  document.querySelectorAll('a[href^="#"]').forEach(link => {
    link.setAttribute('href', location.pathname + location.search + link.getAttribute('href'));
  });
  document.querySelectorAll('[data-ui-navigate]').forEach(select => select.addEventListener('change', () => { location.href = select.value; }));
  const products = document.querySelector('[data-products]');
  const sidebarShell = document.querySelector('.ui-sidebar-shell');
  if (sidebarShell) {
    const small = matchMedia('(max-width:900px)');
    const composeSidebar = () => { sidebarShell.open = !small.matches; };
    composeSidebar(); small.addEventListener('change', composeSidebar);
  }
  function setView(view) {
    if (!products) return;
    products.dataset.layout = view;
    document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
  }
  try { setView(localStorage.getItem('energostor-product-view') === 'grid' ? 'grid' : 'list'); } catch (_) { setView('list'); }
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
    setView(button.dataset.view);
    try { localStorage.setItem('energostor-product-view', button.dataset.view); } catch (_) {}
  }));
  document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(button.dataset.copy); button.textContent = 'Скопировано'; announce.textContent = 'Артикул скопирован'; }
    catch (_) { announce.textContent = 'Выделите и скопируйте артикул вручную'; }
  }));
  document.querySelectorAll('[data-product-request]').forEach(button => button.addEventListener('click', () => {
    const message = document.querySelector('#lead-form [name="message"]');
    const quantity = document.getElementById('quote-quantity');
    const count = Math.max(1, parseInt(quantity?.value, 10) || 1);
    if (message) message.value = `Оборудование: ${button.dataset.productRequest}\nАртикул: ${button.dataset.productModel}\nКоличество: ${count}\n${location.origin + location.pathname}`;
  }));
  const query = document.querySelector('[data-brand-search]');
  const vendorQuery = document.querySelector('#vendor-query');
  const requestedVendor = new URLSearchParams(location.search).get('brand');
  if (vendorQuery && requestedVendor) {
    vendorQuery.value = requestedVendor.slice(0,100);
    vendorQuery.dispatchEvent(new Event('input',{bubbles:true}));
  }
  if (query) {
    const brands = [...document.querySelectorAll('[data-brand-name]')];
    const groups = [...document.querySelectorAll('[data-brand-group]')];
    const status = document.querySelector('[data-brand-status]');
    const empty = document.querySelector('[data-brand-empty]');
    const filter = () => {
      const term = query.value.trim().toLocaleLowerCase('ru'); let count = 0;
      for (const brand of brands) { brand.hidden = !brand.dataset.brandName.toLocaleLowerCase('ru').includes(term); if (!brand.hidden) count++; }
      for (const group of groups) group.hidden = !group.querySelector('[data-brand-name]:not([hidden])');
      const ending = count % 100 >= 11 && count % 100 <= 14 ? 'производителей' : count % 10 === 1 ? 'производитель' : count % 10 >= 2 && count % 10 <= 4 ? 'производителя' : 'производителей';
      if (status) status.textContent = `${count} ${ending}`;
      if (empty) empty.hidden = count > 0;
    };
    query.addEventListener('input', filter); filter();
  }
  const content = document.querySelector('.ui-information-content');
  const toc = document.querySelector('[data-page-toc]');
  if (content && toc) {
    const headings = [...content.querySelectorAll('h2,h3')].filter(h => h.textContent.trim()).slice(0, 16);
    if (headings.length >= 2) {
      headings.forEach((heading, index) => {
        if (!heading.id) heading.id = `section-${index + 1}`;
        const link = document.createElement('a'); link.href = `${location.pathname}#${heading.id}`; link.textContent = heading.textContent.trim();
        toc.querySelector('div').append(link);
      });
      toc.hidden = false;
    }
  }
  const links = document.querySelectorAll('.nav > a, .ui-footer nav a');
  for (const link of links) if (new URL(link.href).pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '')) link.setAttribute('aria-current', 'page');
  // Keep the expanded catalogue inside the actual header/viewport geometry.
  const header = document.querySelector('.site-header');
  if (header && window.ResizeObserver) new ResizeObserver(() => {
    document.documentElement.style.setProperty('--ui-header-height', `${header.getBoundingClientRect().height}px`);
  }).observe(header);
  // Broken remote photos should never leave an oversized broken-image marker.
  document.querySelectorAll('.ui-product-thumb img,.ui-product-visual img').forEach(img => {
    const fail = () => { img.hidden = true; img.closest('a')?.classList.add('ui-image-unavailable'); };
    img.addEventListener('error', fail); if (img.complete && img.naturalWidth === 0) fail();
  });
})();
