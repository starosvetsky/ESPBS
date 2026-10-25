'use strict';
const $ = selector => document.querySelector(selector);
const text = (tag, value, className) => {const node=document.createElement(tag);node.textContent=value ?? '';if(className)node.className=className;return node;};
const display = value => typeof value === 'object' ? JSON.stringify(value,null,2) : String(value ?? '—');
const date = value => value ? new Date(value).toLocaleString('ru-RU') : '—';
let cursors=[''], page=0, result=null, busy=false, activeBatch='', activeQuery='';
async function api(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error(`Не удалось прочитать хранилище (${response.status}). Проверьте подключение и вход в панель.`);return response.json();}
function link(label,url,parent){try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol)||parsed.username||parsed.password)return;const a=text('a',label);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);}catch{}}
function showCard(item){
  const p=item.product, content=$('#card-content');content.replaceChildren();
  const title=text('h2',p.name || 'Без названия');title.id='card-title';content.append(title);
  content.append(text('p',`Сохранено: ${date(item.collected_at)} · Партия ${item.batch_id}`));
  const fields=document.createElement('dl');
  for(const [name,value] of [['Бренд',p.brand || p.manufacturer],['Артикул / MPN',p.mpn || p.article || p.sku],['Цена',p.offer?.price_text || p.offer?.price],['Наличие',p.offer?.availability]]){fields.append(text('dt',name),text('dd',display(value)));}content.append(fields);
  // Images remain external links, never imply that binary files are stored locally.
  const photos=text('section','');photos.append(text('h3','Фотографии'));
  let photoCount=0;
  for(const url of Array.isArray(p.images)?p.images:[]){try{const u=new URL(url);if(u.hostname==='olnisa.ru'||u.hostname.endsWith('.olnisa.ru'))continue;link(`Фото ${++photoCount}`,url,photos);}catch{}}
  if(!photoCount)photos.append(text('p','Ссылок на фотографии нет'));content.append(photos);
  if(p.description)content.append(text('h3','Описание'),text('p',display(p.description),'description'));
  content.append(text('h3','Характеристики'));const attrs=document.createElement('dl');
  for(const [key,value] of Object.entries(p.attributes || {}))attrs.append(text('dt',key),text('dd',display(value)));
  content.append(attrs.childElementCount?attrs:text('p','Характеристики не сохранены'));
  for(const doc of Array.isArray(p.documents)?p.documents:[])link(doc.name || 'Документ',doc.url,content);
  const raw=document.createElement('details');raw.append(text('summary','Все поля карточки'),text('pre',JSON.stringify(p,null,2)));content.append(raw);
  $('#card').showModal();
}
function controls(){for(const el of $('#filters').elements)el.disabled=busy;$('#prev').disabled=busy||page===0;$('#next').disabled=busy||!result?.has_more;}
async function load(){
  busy=true;result=null;controls();$('#status').textContent='Загрузка товаров…';$('#listing').replaceChildren();
  try{
    const query=new URLSearchParams({batch:activeBatch,q:activeQuery,after:cursors[page],limit:'30'});
    result=await api(`api/inventory/products?${query}`);
    for(const item of result.products){const p=item.product,node=text('article','','inventory-item');node.append(text('small',date(item.collected_at)),text('h2',p.name || 'Без названия'),text('p',[p.brand || p.manufacturer,p.mpn || p.article || p.sku].filter(Boolean).map(display).join(' · ')),text('p',p.offer?.price_text || 'Цена не указана'));const button=text('button','Открыть карточку');button.onclick=()=>showCard(item);node.append(button);$('#listing').append(node);}
    $('#status').textContent=result.products.length?`Записей на странице: ${result.products.length}`:(activeQuery?'По этому запросу ничего не найдено.':'В выбранных партиях пока нет сохранённых товаров.');
    $('#page').textContent=`Страница ${page+1}`;
  }catch(error){$('#status').textContent=error.message;$('#page').textContent='';}finally{busy=false;controls();}
}
async function refresh(){
  busy=true;result=null;controls();$('#listing').replaceChildren();$('#totals').textContent='Проверка хранилища…';
  try{const data=await api('api/inventory/batches');const selected=$('#batch').value;$('#batch').replaceChildren(new Option('Все партии',''));for(const batch of data.batches){$('#batch').add(new Option(`${date(batch.created_at)} · записей: ${batch.record_count} · ${batch.id.slice(0,8)}`,batch.id));}if(data.batches.some(b=>b.id===selected))$('#batch').value=selected;$('#totals').textContent=`Записей: ${data.record_count.toLocaleString('ru-RU')} · Партий: ${data.batches.length}`;activeBatch=$('#batch').value;activeQuery=$('#query').value.trim();page=0;cursors=[''];await load();}
  catch(error){$('#totals').textContent='Хранилище недоступно';$('#status').textContent=error.message;busy=false;controls();}
}
$('#filters').onsubmit=event=>{event.preventDefault();activeBatch=$('#batch').value;activeQuery=$('#query').value.trim();page=0;cursors=[''];load();};
$('#reload').onclick=refresh;
$('#prev').onclick=()=>{if(!busy&&page>0){page--;load();}};
$('#next').onclick=()=>{if(!busy&&result?.has_more){cursors[++page]=result.next_cursor;load();}};
$('#close').onclick=()=>$('#card').close();
refresh();
