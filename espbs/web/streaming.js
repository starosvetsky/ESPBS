Object.assign(stateName, {WAITING_PARTS:'Ожидает очистки частей', PAUSED_JOURNAL:'Предел журнала'});
let streamJob=null, streamCursors=[0], streamRequest=0;
function streamNode(tag, text, parent) {
  const node=document.createElement(tag);node.textContent=text;parent.append(node);return node;
}
function renderStreaming(job) {
  let box=$('#stream-controls');
  if(!box){box=document.createElement('section');box.id='stream-controls';box.className='archive';$('#detail').insertBefore(box,$('#detail').querySelector('.columns'));}
  if(streamJob!==job.id){streamJob=job.id;streamCursors=[0];++streamRequest;box.replaceChildren();}
  box.hidden=!job.stream;
  if(!job.stream)return;
  const stream=job.stream,budget=stream.budget;
  $('#prepare').disabled=true;$('#include-files').disabled=true;$('#cleanup').disabled=true;
  $('#archive-status').textContent='Скачивайте отдельные части ниже';
  $('#archive-meta').textContent='Исходная партия и журнал сохраняются. Откройте часть для подготовки ZIP, проверки копии и отдельной очистки.';
  $('#resume').disabled=!['READY','STOPPED','FAILED','PAUSED_DISK','WAITING_PARTS'].includes(job.state)||stream.occupied>=stream.window;
  if(!box.querySelector('.stream-summary')){
    const summary=streamNode('div','',box);summary.className='stream-summary';
    const list=streamNode('div','',box);list.className='stream-list';
  }
  const summary=box.querySelector('.stream-summary');summary.replaceChildren();
  streamNode('strong',`Части журнала: занято ${stream.occupied} из ${stream.window} мест`,summary);
  streamNode('p',`Журнал: ${budget.versions} / ${budget.max_versions} версий · ${formatBytes(budget.payload_bytes)} / ${formatBytes(budget.max_payload_bytes)} JSON. Очистка частей этот счётчик не уменьшает.`,summary);
  const reasons={WAITING_PARTS:'Откройте часть → подготовьте и скачайте ZIP → проверьте копию → подтвердите её → отдельно очистите часть. Затем нажмите «Продолжить».',
    PAUSED_JOURNAL:'Достигнут предел журнала. Сохранённые части можно выгрузить; очистка частей не позволит продолжить эту партию. Нужна новая партия или отдельная доработка хранения истории.',
    PAUSED_DISK:'Недостаточно свободного места. Очистите только части с проверенной копией, затем продолжите сбор.'};
  streamNode('p',reasons[job.state]||'Части формируются во время сбора. ZIP готовится отдельно внутри каждой части; ничего не удаляется автоматически.',summary);
  const prepare=streamNode('button',stream.unfinished?'Повторить подготовку незавершённой части':'Выделить накопленные версии в часть',summary);
  const canPrepare=stream.can_prepare&&job.state!=='RUNNING';
  prepare.disabled=!canPrepare;
  prepare.onclick=async()=>{prepare.disabled=true;try{
    const child=await post(`api/jobs/${job.id}/stream-part`,{after:stream.next_after});
    if(child.id)await select(child.id);else await loadDetail();
  }catch(error){alert(error.message);}finally{prepare.disabled=!canPrepare;}};
  loadStreamParts(job.id,box.querySelector('.stream-list'));
}
async function loadStreamParts(id,box) {
  const request=++streamRequest,after=streamCursors.at(-1);
  try{
    const page=await api(`api/jobs/${id}/stream-parts?limit=10&after=${after}`);
    if(request!==streamRequest||streamJob!==id)return;
    box.replaceChildren();
    if(!page.parts.length)streamNode('p','На этой странице частей пока нет.',box);
    for(const part of page.parts){
      const states={VERIFIED:'копия подтверждена, место ещё занято',CLEANING:'очистка прервана',CLEANED:'очищена'};
      const button=streamNode('button',`Часть ${part.seq}: версии ${part.start_seq+1}–${part.end_seq} · ${part.record_count} карточек · ${states[part.retention_state]||(part.ready?'готова к упаковке':'подготовка не завершена')}`,box);
      button.disabled=!part.ready;button.onclick=()=>select(part.child_id);
    }
    const prev=streamNode('button','Предыдущие части',box);prev.disabled=streamCursors.length===1;
    prev.onclick=()=>{streamCursors.pop();loadStreamParts(id,box);};
    const next=streamNode('button','Следующие части',box);next.disabled=!page.has_more;
    next.onclick=()=>{streamCursors.push(page.next_cursor);loadStreamParts(id,box);};
  }catch(error){if(request===streamRequest&&streamJob===id){box.replaceChildren();streamNode('p',error.message,box);}}
}
