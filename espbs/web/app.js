const $=s=>document.querySelector(s);let selected=null,eventCursor=0,timer,detailBusy=false,productCursors=[''];
const api=async(path,options={})=>{const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options});const data=await response.json();if(!response.ok)throw new Error(data.error||'Ошибка API');return data};
const stateName={PREPARING:'Подготовка части',PAUSED_DISK:'Мало места',READY:'Готово',RUNNING:'Выполняется',STOPPED:'Остановлено',COMPLETED:'Завершено',FAILED:'Ошибка'};
function connection(ok){const el=$('#connection');el.textContent=ok?'API подключён':'Нет соединения';el.className='badge '+(ok?'online':'offline')}
function jobButton(job){const b=document.createElement('button');b.className='job'+(selected===job.id?' active':'');b.innerHTML=`<span><b>${stateName[job.state]||job.state}</b><i>${job.completed}/${job.target ?? 'весь каталог'}</i></span><small>${job.id.slice(0,8)} · ${escapeHtml(sourceLabel(job.source))}</small>`;b.onclick=()=>select(job.id);return b}
let jobCursors=[''],jobsRequest=0;
async function loadJobs(){
 const request=++jobsRequest;
 try{
  const data=await api(`api/jobs?limit=25&after=${encodeURIComponent(jobCursors.at(-1))}`);
  if(request!==jobsRequest)return;
  connection(true);
  const box=$('#jobs');box.innerHTML='';
  data.jobs.forEach(j=>box.append(jobButton(j)));
  if(!data.jobs.length)box.innerHTML='<p class="empty">Заданий пока нет</p>';
  const nav=document.createElement('div');nav.className='section-title';
  for(const [label,enabled,action] of [
   ['Назад',jobCursors.length>1,()=>jobCursors.pop()],
   ['Дальше',data.has_more,()=>jobCursors.push(data.next_cursor)],
   ['К новым',jobCursors.length>1,()=>{jobCursors=['']}]
  ]){
   const button=document.createElement('button');button.className='ghost';
   button.textContent=label;button.disabled=!enabled;
   button.onclick=()=>{action();loadJobs()};nav.append(button);
  }
  box.append(nav);
 }catch(e){if(request===jobsRequest)connection(false)}
}
async function select(id){selected=id;eventCursor=0;productCursors=[''];await loadJobs();await loadDetail()}
function render(job){
 const host=$('#detail');if(!host.querySelector('#job-title'))host.replaceChildren($('#detail-template').content.cloneNode(true));
 $('#job-title').textContent=job.id;$('#state').textContent=stateName[job.state]||job.state;
 $('#discovered').textContent=job.discovered;$('#completed').textContent=job.completed;$('#target').textContent=job.target ?? 'Весь каталог';
 $('#error').textContent=[job.error,job.source_warning].filter(Boolean).join(' · ');
 $('#stop').disabled=job.state!=='RUNNING';$('#resume').disabled=!['STOPPED','FAILED','READY','PAUSED_DISK'].includes(job.state);
 $('#stop').onclick=()=>action('stop');$('#resume').onclick=()=>action('resume');
 renderArchive(job);renderRetention(job);
}
function renderArchive(job){
 if(!$('#include-files')){
  const label=document.createElement('label');label.id='include-files-label';
  const input=document.createElement('input');input.type='checkbox';input.id='include-files';
  label.append(input,document.createTextNode(' Скачать PDF и фото в ZIP (до 50 адресов, 256 МБ; пропуски — в отчёте)'));
  $('#prepare').before(label);
 }
 const ready=job.archive?.ready,task=job.archive?.task||{},busy=['QUEUED','RUNNING'].includes(task.state);
 $('#include-files-label').hidden=Boolean(ready);$('#include-files').disabled=busy;
 $('#prepare').hidden=Boolean(ready);$('#prepare').disabled=job.state!=='COMPLETED'||busy;
 $('#prepare').textContent=busy?'Подготовка на сервере…':'Подготовить ZIP/XML';$('#prepare').onclick=prepareArchive;
 $('#download').hidden=!ready;$('#download').href=`api/jobs/${job.id}/archive`;
 $('#archive-status').textContent=ready?'ZIP/XML готов к скачиванию':busy?'Скачиваются материалы и собирается архив':task.error||'Архив ещё не подготовлен';
 const summary=job.archive?.attachment_summary;
 const files=summary?` · файлов ${summary.unique_files} · ссылок с файлами ${summary.embedded}, пропущено ${summary.skipped}, ошибок ${summary.failed}`:' · вложения только ссылками';
 $('#archive-meta').textContent=ready?`${job.archive.record_count} товаров · ${formatBytes(job.archive.size)}${files} · SHA-256 ${job.archive.sha256.slice(0,12)}…`:busy?'Можно закрыть страницу. Подготовка продолжится на сервере.':'Исходные записи сохраняются. Готовый архив не перезаписывается. Разрешены сайт-источник и поддомены зарегистрированного производителя.';
}
async function loadDetail(){
 if(!selected||detailBusy)return;detailBusy=true;const id=selected;const cursor=productCursors[productCursors.length-1];
 try{
  const [job,products,events]=await Promise.all([api(`api/jobs/${id}`),api(`api/jobs/${id}/products?limit=50&after=${encodeURIComponent(cursor)}`),api(`api/jobs/${id}/events?after=${eventCursor}&limit=100`)]);
  if(id!==selected||cursor!==productCursors[productCursors.length-1])return;render(job);
  const box=$('#products');const fingerprint=JSON.stringify(products.products);
  if(box.dataset.content!==fingerprint){box.replaceChildren(...products.products.map(x=>productPreview(x.product)));box.dataset.content=fingerprint;if(!products.products.length)box.innerHTML='<p class="empty">Товаров пока нет</p>';}
  $('#product-page').textContent=`Страница ${productCursors.length} · сохранено ${job.completed}`;
  $('#prev-products').disabled=productCursors.length===1;$('#next-products').disabled=!products.has_more;
  $('#prev-products').onclick=()=>{if(productCursors.length>1){productCursors.pop();loadDetail();}};
  $('#next-products').onclick=()=>{if(products.has_more){productCursors.push(products.next_cursor);loadDetail();}};
  if(eventCursor===0)$('#events').innerHTML='';
  for(const e of events.events){const div=document.createElement('div');div.className='event';div.innerHTML=`<time>${new Date(e.time).toLocaleTimeString()}</time><span>${escapeHtml(e.kind)}${e.status?' · '+escapeHtml(e.status):''}${e.error?' · '+escapeHtml(e.error):''}</span>`;$('#events').append(div)}
  while($('#events').childElementCount>300)$('#events').firstElementChild.remove();
  eventCursor=events.next_cursor;connection(true);
 }catch(e){connection(false)}finally{detailBusy=false}
}
const escapeHtml=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formatBytes=value=>value<1024?`${value} Б`:value<1024*1024?`${(value/1024).toFixed(1)} КБ`:`${(value/1024/1024).toFixed(1)} МБ`;
async function action(name){try{await api(`api/jobs/${selected}/${name}`,{method:'POST',body:'{}'});await loadJobs();await loadDetail()}catch(e){alert(e.message)}}
async function prepareArchive(){const button=$('#prepare');button.disabled=true;button.textContent='Подготовка…';try{await api(`api/jobs/${selected}/archive`,{method:'POST',body:JSON.stringify({include_files:$('#include-files').checked})});await loadJobs();await loadDetail()}catch(e){button.disabled=false;button.textContent='Подготовить ZIP/XML';alert(e.message)}}
$('#refresh').onclick=()=>{loadJobs();loadDetail()};
timer=setInterval(()=>{loadJobs();loadDetail()},2000);

async function loadStorage(){try{const d=await api('api/storage');$('#storage').textContent=`Диск: свободно ${formatBytes(d.free_bytes)} · резерв ${formatBytes(d.reserve_bytes)} · данные ${formatBytes(d.sizes.batches+d.sizes.jobs+(d.sizes.directory||0))} · архивы ${formatBytes(d.sizes.exports)}. ${d.can_collect?'Сбор разрешён.':'Сбор приостановлен: недостаточно места.'}`;window.diskCanCollect=d.can_collect;if(typeof updateStartState==='function')updateStartState()}catch(e){$('#storage').textContent='Не удалось получить состояние диска';window.diskCanCollect=false;$('#start').disabled=true}}
setInterval(loadStorage,5000);

function renderRetention(job){const state=job.retention?.state;$('#retention-status').textContent=state==='CLEANED'?'Серверные записи и ZIP удалены. История сохранена.':state==='CLEANING'?'Очистка прервана. Нажмите повторно для завершения.':state==='VERIFIED'?'Копия подтверждена. Очистка требует отдельного подтверждения.':'Скачайте архив и проверьте его на компьютере.';$('#confirm-copy').disabled=!job.archive?.ready||['CLEANING','CLEANED'].includes(state);$('#cleanup').disabled=!['VERIFIED','CLEANING'].includes(state);$('#prepare').hidden=Boolean(state)||job.archive?.ready;$('#confirm-copy').onclick=async()=>{try{const f=$('#receipt-file').files[0];if(!f)throw new Error('Выберите receipt.json');if(f.size>16384)throw new Error('Слишком большой отчёт');const report=JSON.parse(await f.text());await api(`api/jobs/${job.id}/confirm-copy`,{method:'POST',body:JSON.stringify(report)});await loadJobs()}catch(e){alert(e.message)}};$('#cleanup').onclick=async()=>{const confirmation=prompt(`Будут удалены товары этой партии и серверный ZIP. Убедитесь, что архив сохранён на компьютере. Для подтверждения введите ID ${job.id}`);if(confirmation===null)return;try{await api(`api/jobs/${job.id}/cleanup`,{method:'POST',body:JSON.stringify({confirmation})});await loadJobs();await loadDetail();await loadStorage()}catch(e){alert(e.message)}}}
