/* Presentation and navigation only. Catalogue data are integrated separately. */
(() => {
  'use strict';
  const root = document.querySelector('[data-menu-browser]');
  if (!root) return;
  const base = root.dataset.base || '';
  const url = path => base + path;
  const old = path => 'https://energostor.ru/' + path;
  const illustratedCategories = new Set([
    'low-voltage',
    'switchgear',
    'automation',
    'drives',
    'power',
    'metering',
    'cable',
    'wiring',
    'lighting',
    'network',
    'components',
    'tooling',
    'other',
  ]);
  let groups = [];
  const list = root.querySelector('[data-menu-list]');
  const panel = root.querySelector('[data-menu-content]');
  const preview = root.querySelector('[data-menu-preview]');
  const title = root.querySelector('[data-menu-title]');
  const note = root.querySelector('[data-menu-note]');
  const all = root.querySelector('[data-menu-all]');
  const image = root.querySelector('[data-menu-image]');
  const previewLink = root.querySelector('[data-menu-preview-link]');
  function el(tag, cls, text) {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
  function select(group) {
    title.textContent=group.name;note.textContent=group.note;
    all.href=group.href;all.textContent='Смотреть раздел →';
    previewLink.href=group.href;
    previewLink.textContent='Перейти в раздел ↗';
    preview.classList.toggle('has-image',!!group.image);
    image.hidden=!group.image;
    if(group.image){image.src=group.image;image.alt='';}
    else{image.removeAttribute('src');image.alt='';}
    root.querySelector('[data-menu-preview-name]').textContent=group.name;
    root.querySelector('[data-menu-preview-number]').textContent=String(groups.indexOf(group)+1).padStart(2,'0');
    panel.replaceChildren();
    for(const [heading,links] of group.sections){
      if(!links.length)continue;const section=el('section','nav-browser__section');section.append(el('h3','',heading));
      const ul=el('ul');for(const [name,path,local] of links){const li=el('li');const a=el('a','',name);a.href=local?path:old(path);li.append(a);ul.append(li);}section.append(ul);panel.append(section);
    }
    for(const b of list.querySelectorAll('button')){const active=b.dataset.category===group.id;b.classList.toggle('is-active',active);b.tabIndex=active?0:-1;b.setAttribute('aria-pressed',String(active));}
  }
  list.addEventListener('keydown',e=>{
    if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
    const buttons=[...list.querySelectorAll('button')];if(!buttons.length)return;e.preventDefault();const current=buttons.indexOf(document.activeElement);const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(current+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();
  });
  const mobile=document.querySelector('[data-mobile-categories]');
  const shade=el('button','menu-shade');shade.type='button';shade.hidden=true;shade.tabIndex=-1;shade.setAttribute('aria-label','Закрыть меню');document.body.append(shade);
  const trigger=document.querySelector('.nav__link--toggle');
  shade.addEventListener('click',()=>{if(!root.hidden&&trigger)trigger.click();});
  new MutationObserver(()=>{shade.hidden=root.hidden;}).observe(root,{attributes:true,attributeFilter:['hidden']});
  window.addEventListener('resize',()=>{if(innerWidth<=900&&!root.hidden&&trigger)trigger.click();});
  function mount(meta){
    groups=meta.categories.map(c=>({id:c.slug,name:c.title,note:CatalogUtil.productsText(c.count),href:url('catalog/?category='+encodeURIComponent(c.slug)),image:illustratedCategories.has(c.slug)?url('assets/img/menu-categories/'+c.slug+'.webp'):null,sections:[['Подразделы',c.children.slice(0,Math.ceil(c.children.length/2)).map(x=>[x.title,url('catalog/?category='+encodeURIComponent(x.slug)),true])],['Ещё в разделе',c.children.slice(Math.ceil(c.children.length/2)).map(x=>[x.title,url('catalog/?category='+encodeURIComponent(x.slug)),true])]]}));
    list.replaceChildren();if(mobile)mobile.replaceChildren();
    for(const group of groups){
      const b=el('button','nav-browser__category');b.type='button';b.dataset.category=group.id;b.setAttribute('aria-controls','menu-category-content');
      b.append(el('span','',group.name),el('span','nav-browser__category-arrow','↗'));
      for(const event of ['mouseenter','focus','click'])b.addEventListener(event,()=>select(group));list.append(b);
      if(mobile){const details=el('details');details.append(el('summary','',group.name));const ul=el('ul');const li=el('li');const all=el('a','','Все товары раздела');all.href=group.href;li.append(all);ul.append(li);for(const [,links] of group.sections){for(const [name,path] of links){const item=el('li');const a=el('a','',name);a.href=path;item.append(a);ul.append(item);}}details.append(ul);mobile.append(details);}
    }
    if(groups.length)select(groups[0]);
  }
  root.querySelector('[data-menu-title]').textContent='Загрузка разделов…';
  CatalogAPI.meta().then(mount).catch(()=>{
    root.querySelector('[data-menu-title]').textContent='Не удалось загрузить разделы';
    root.querySelector('[data-menu-note]').textContent='Откройте каталог или обновите страницу.';
    all.href=url('catalog/');all.textContent='Открыть каталог →';preview.hidden=true;
  });
})();
