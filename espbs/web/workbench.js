let checkedSignature = null, probeBusy = false;
const post = (path, body) => api(path, {method:'POST', body:JSON.stringify(body)});
function selectorsValue(id) {return JSON.parse($(id).value.trim() || '{}');}
function signature() {return JSON.stringify([$('#start-url').value.trim(), $('#selectors').value]);}
function updateStartState() {$('#start').disabled = probeBusy || !window.diskCanCollect || checkedSignature !== signature();}
for (const id of ['#start-url','#selectors']) $(id).addEventListener('input',()=>{checkedSignature=null;updateStartState();});
$('#probe').onclick = async () => {
  checkedSignature=null;probeBusy=true;updateStartState();$('#probe').disabled=true;
  $('#source-help').textContent='Проверяем страницу и до трёх карточек…';
  const requested=signature();
  try {
    const raw=$('#selectors').value.trim();
    const result=await post('api/probe',{url:$('#start-url').value.trim(),...(raw?{selectors:selectorsValue('#selectors')}:{})});
    if(requested!==signature())return;
    if(!raw&&result.config.selectors&&Object.keys(result.config.selectors).length)$('#selectors').value=JSON.stringify(result.config.selectors,null,2);
    const box=$('#probe-result');box.replaceChildren();
    const heading=document.createElement('h3');heading.textContent=`Пробный разбор: ${result.samples.length} образцов · найдено ссылок: ${result.discovered}`;box.append(heading);
    const cards=document.createElement('div');cards.className='sample-grid';result.samples.forEach(p=>cards.append(productPreview(p)));box.append(cards);
    for(const error of result.errors){const p=document.createElement('p');p.className='error';p.textContent=`${error.url}: ${error.error}`;box.append(p);}
    checkedSignature=result.can_start?signature():null;
    $('#source-help').textContent=result.can_start?'Проверьте название, бренд и артикул в образцах. Можно запускать партию.':'Образцы не распознаны. Уточните правила сайта.';
  } catch(error){$('#source-help').textContent=error.message;}
  finally {probeBusy=false;$('#probe').disabled=false;updateStartState();}
};
$('#save-profile').onclick=async()=>{try{
  await post('api/profiles',{url:$('#start-url').value.trim(),selectors:selectorsValue('#selectors')});
  $('#source-help').textContent='Правила сохранены. Выполните пробный разбор.';checkedSignature=null;updateStartState();
}catch(error){$('#source-help').textContent=error.message;}};
$('#new-job').onsubmit=async e=>{
  e.preventDefault();if(checkedSignature!==signature())return;
  $('#start').disabled=true;
  try{
    const raw=$('#selectors').value.trim();
    const job=await post('api/jobs',{source:'auto',start_url:$('#start-url').value.trim(),limit:Number($('#limit').value),
      auto_enrich:$('#auto-enrich').checked,...(raw?{selectors:selectorsValue('#selectors')}:{})});
    await select(job.id);
  }catch(error){$('#source-help').textContent=error.message;}
  finally{updateStartState();}
};
async function loadDirectory(){
  try{
    const data=await api('api/directory');const list=$('#manufacturers');list.replaceChildren();$('#brand-list').replaceChildren();
    for(const entry of data.manufacturers){
      const button=document.createElement('button');button.className='ghost';button.textContent=`${entry.brand} · ${new URL(entry.home_url).hostname} — изменить`;
      button.onclick=()=>{$('#brand').value=entry.brand;$('#home-url').value=entry.home_url;$('#url-template').value=entry.template;$('#official-selectors').value=Object.keys(entry.selectors).length?JSON.stringify(entry.selectors,null,2):'';};list.append(button);
      const option=document.createElement('option');option.value=entry.brand;$('#brand-list').append(option);
    }
    $('#mappings').replaceChildren(...data.mappings.map(entry=>{const p=document.createElement('p');p.textContent=`${entry.brand} · ${entry.mpn} · ${entry.url}`;return p;}));
  }catch(error){$('#directory-status').textContent=error.message;}
}
$('#manufacturer-form').onsubmit=async e=>{e.preventDefault();try{
  await post('api/manufacturers',{brand:$('#brand').value,home_url:$('#home-url').value,template:$('#url-template').value,selectors:selectorsValue('#official-selectors')});
  $('#directory-status').textContent='Производитель сохранён. Можно обогатить ранее собранные товары.';await loadDirectory();
}catch(error){$('#directory-status').textContent=error.message;}};
$('#mapping-form').onsubmit=async e=>{e.preventDefault();try{
  await post('api/mappings',{brand:$('#mapping-brand').value,mpn:$('#mapping-mpn').value,url:$('#mapping-url').value});
  $('#directory-status').textContent='Ссылка сохранена. Совпадение будет проверено при обогащении.';await loadDirectory();
}catch(error){$('#directory-status').textContent=error.message;}};
const originalRender = render;
render = function(job){
  originalRender(job);
  let box=$('#enrichment-controls');
  if(!box){box=document.createElement('div');box.id='enrichment-controls';box.className='archive';$('#detail').insertBefore(box,$('#detail').querySelector('.metrics'));}
  const fingerprint=JSON.stringify([job.id,job.state,job.retention?.state,job.child_id,job.enrichment_counts]);
  if(box.dataset.state===fingerprint)return;
  box.dataset.state=fingerprint;
  box.replaceChildren();
  const label=document.createElement('span');label.textContent=job.source==='enrichment'?'Обогащение по брендам · исходная партия '+job.parent_id:'Сбор: '+(job.start_url || 'Eltex');box.append(label);
  const button=document.createElement('button');button.textContent='Дополнить данными производителей';button.disabled=job.state!=='COMPLETED'||['CLEANING','CLEANED'].includes(job.retention?.state);
  button.onclick=async()=>{button.disabled=true;try{const child=await post(`api/jobs/${job.id}/enrich`,{});await select(child.id);}catch(error){alert(error.message);button.disabled=false;}};box.append(button);
  if(job.child_id){const child=document.createElement('button');child.textContent='Открыть обогащённую партию';child.onclick=()=>select(job.child_id);box.append(child);}
  if(job.source==='enrichment' && job.enrichment_counts){
    const text=document.createElement('small');const labels={MATCHED:'Совпало',NO_MANUFACTURER:'Нет производителя',NEEDS_MAPPING:'Нужна ссылка',MISSING_IDENTITY:'Нет бренда/MPN',MISMATCH:'Не совпало',ERROR:'Ошибка'};
    text.textContent=Object.entries(job.enrichment_counts).map(([k,v])=>`${labels[k]||k}: ${v}`).join(' · ');box.append(text);
  }
};
loadDirectory();updateStartState();
