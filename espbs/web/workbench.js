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
updateStartState();
