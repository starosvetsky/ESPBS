let submitBusy = false;
const post = (path, body) => api(path, {method:'POST', body:JSON.stringify(body)});
function updateStartState() {$('#start').disabled = submitBusy || !window.diskCanCollect || !$('#start-url').validity.valid;}
$('#start-url').addEventListener('input',updateStartState);
$('#new-job').onsubmit=async e=>{
  e.preventDefault();if(submitBusy)return;
  submitBusy=true;updateStartState();
  try{
    const job=await post('api/jobs',{source:'auto',start_url:$('#start-url').value.trim(),limit:null,
      auto_enrich:true,photo_policy:$('#photo-policy').value});
    await select(job.id);
  }catch(error){$('#source-help').textContent=error.message;}
  finally{submitBusy=false;updateStartState();}
};
const originalRender = render;
render = function(job){
  originalRender(job);
  let box=$('#enrichment-controls');
  if(!box){box=document.createElement('div');box.id='enrichment-controls';box.className='archive';$('#detail').insertBefore(box,$('#detail').querySelector('.metrics'));}
  const fingerprint=JSON.stringify([job.id,job.state,job.retention?.state,job.child_id,job.enrichment_counts,job.coverage,job.archive_parts,job.archive_queue]);
  if(box.dataset.state===fingerprint)return;
  box.dataset.state=fingerprint;
  box.replaceChildren();
  const label=document.createElement('span');label.textContent=job.source==='archive-part'?'Архивная часть · исходная партия '+job.parent_id:job.source==='enrichment'?'Обогащение по брендам · исходная партия '+job.parent_id:'Сбор: '+(job.start_url || 'Eltex');box.append(label);
  const coverage=document.createElement('small');const c=job.coverage;
  coverage.textContent=c?.measured?`Заполненность ${c.measured} карточек: фото ${c.images||0}, документы ${c.documents||0}, характеристики ${c.attributes||0}, описание ${c.description||0}. Завершение задания не означает полноту карточек.`:'Заполненность этой партии не измерялась; завершение задания не означает полноту карточек.';
  box.append(coverage);
  const button=document.createElement('button');button.textContent='Дополнить данными производителей';button.disabled=job.state!=='COMPLETED'||['CLEANING','CLEANED'].includes(job.retention?.state);
  button.onclick=async()=>{button.disabled=true;try{const child=await post(`api/jobs/${job.id}/enrich`,{});await select(child.id);}catch(error){alert(error.message);button.disabled=false;}};box.append(button);
  if(job.source==='archive-part'){
    const parent=document.createElement('button');parent.textContent='К исходной партии и следующей части';parent.onclick=()=>select(job.parent_id);box.append(parent);
  }else{
    const parts=job.archive_parts||{};
    const queue=job.archive_queue||{},active=['QUEUED','RUNNING'].includes(queue.state);
    const queueNames={QUEUED:'Запускается',RUNNING:'Готовит архивы',WAITING_DOWNLOAD:'Ждёт скачивания и отдельной очистки частей',PAUSED_DISK:'Пауза: мало места',STOPPED:'Остановлена',FAILED:'Ошибка',REVIEW:'Нужна проверка отчёта',COMPLETED:'Очередь завершена'};
    const queueInfo=document.createElement('small');queueInfo.textContent=`Очередь: ${queueNames[queue.state]||'не запущена'}. Обработано частей: ${queue.last_seq||0}; неполных: ${queue.incomplete_parts||0}. ${queue.error||''}`;box.append(queueInfo);
    const queueStart=document.createElement('button');queueStart.textContent=queue.state==='REVIEW'?'Продолжить очередь после проверки отчёта':'Готовить части автоматически (до двух вперёд)';
    queueStart.disabled=job.state!=='COMPLETED'||active||queue.state==='COMPLETED'||['CLEANING','CLEANED'].includes(job.retention?.state);
    queueStart.onclick=async()=>{queueStart.disabled=true;try{await post(`api/jobs/${job.id}/archive-queue-start`,{});await loadDetail();}catch(error){alert(error.message);queueStart.disabled=false;}};box.append(queueStart);
    if(active){const stopQueue=document.createElement('button');stopQueue.textContent=queue.stop?'Остановится после текущей части':'Остановить после текущей части';stopQueue.disabled=Boolean(queue.stop);stopQueue.onclick=async()=>{stopQueue.disabled=true;try{await post(`api/jobs/${job.id}/archive-queue-stop`,{});await loadDetail();}catch(error){alert(error.message);stopQueue.disabled=false;}};box.append(stopQueue);}
    const split=document.createElement('button');split.textContent=parts.done?'Все карточки распределены по частям':'Создать следующую архивную часть';
    split.disabled=job.state!=='COMPLETED'||parts.done||active||['CLEANING','CLEANED'].includes(job.retention?.state);
    split.onclick=async()=>{split.disabled=true;try{const child=await post(`api/jobs/${job.id}/archive-part`,{after:parts.next_cursor||''});await select(child.id);}catch(error){alert(error.message);split.disabled=false;}};box.append(split);
    const hint=document.createElement('small');hint.textContent=`Создано частей: ${parts.count||0}. До 25 карточек и примерно 40 ссылок на материалы в части. Без повторного парсинга; исходная партия сохраняется.`;box.append(hint);
    for(const part of parts.recent||[]){const open=document.createElement('button');open.textContent=`Часть ${part.seq}: ${part.record_count} карточек · ${part.ready?'готова к упаковке':'нужно повторить подготовку'}`;open.onclick=()=>select(part.child_id);box.append(open);}
  }
  if(job.child_id){const child=document.createElement('button');child.textContent='Открыть обогащённую партию';child.onclick=()=>select(job.child_id);box.append(child);}
  if(job.source==='enrichment' && job.enrichment_counts){
    const text=document.createElement('small');const labels={MATCHED:'Совпало',NO_MANUFACTURER:'Нет производителя',NEEDS_MAPPING:'Нужна ссылка',MISSING_IDENTITY:'Нет бренда/MPN',MISMATCH:'Не совпало',ERROR:'Ошибка'};
    text.textContent=Object.entries(job.enrichment_counts).map(([k,v])=>`${labels[k]||k}: ${v}`).join(' · ');box.append(text);
  }
};
updateStartState();
