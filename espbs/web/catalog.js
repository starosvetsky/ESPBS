let sourceRegistry = [];
const sourceLabel = id => id === 'archive-part' ? 'Архивная часть' : id === 'enrichment' ? 'Обогащение по брендам' : id === 'generic' ? 'Сбор по ссылке' : sourceRegistry.find(x => x.id === id)?.name || id || 'Eltex';
async function loadSources() {
  try {sourceRegistry=(await api('api/sources')).sources;await loadStorage();await loadJobs();}
  catch(error){$('#source-help').textContent=error.message;}
}
function safeLink(url) {
  try { const u = new URL(url); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
}
function productPreview(product) {
  const node = document.createElement('div'); node.className = 'product';
  const image = (product.images || []).find(url => {
    try { const u=new URL(url);const source=product.provenance?.images?.source_url || (product.enrichment?.status==='MATCHED'?product.enrichment.source_url:product.source==='eltex'?product.source_url:null);if(!source)return false;const base=new URL(source);const allowed=u.origin===base.origin || (base.hostname==='shop.nag.ru'&&u.hostname==='cdn.nag.shop');return allowed&&u.protocol==='https:'&&!u.username&&!u.password&&!u.hostname.endsWith('olnisa.ru'); } catch { return false; }
  });
  const status = product.enrichment?.status;
  const label = status === 'SOURCE_OFFICIAL' ? 'С официального сайта' : status === 'MATCHED' ? 'Официальные данные подтверждены' : status === 'ERROR' ? 'Ошибка обогащения' : status && status !== 'MATCHED' ? 'Нужно проверить соответствие' : product.quality?.status === 'GOOD' ? 'Проверено' : 'Требует проверки';
  node.innerHTML = `${image ? `<img loading="lazy" src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}">` : '<div class="no-photo">Нет фото по выбранному правилу</div>'}<strong>${escapeHtml(product.name)}</strong><span>${escapeHtml(label)}</span><p>${escapeHtml(product.offer?.price_text || '')} ${escapeHtml(product.offer?.availability || '')}</p><details><summary>Описание и характеристики</summary><p>${escapeHtml(product.description || '')}</p><dl>${Object.entries(product.attributes || {}).map(([key,value])=>`<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(Array.isArray(value)?value.join('; '):value)}</dd>`).join('')}</dl><p>${(product.quality?.issues || []).map(escapeHtml).join('<br>')}</p></details>`;
  const img = node.querySelector('img');
  if (img) img.onerror = () => { const text=document.createElement('div');text.className='no-photo';text.textContent='Фото временно недоступно';img.replaceWith(text); };
  const details = node.querySelector('details');
  if(product.coverage?.missing?.length){const p=document.createElement('p');const labels={images:'фото',documents:'документы',attributes:'характеристики',description:'описание'};p.textContent='Не собрано: '+product.coverage.missing.map(k=>labels[k]||k).join(', ');details.prepend(p);}
  for (const [title,url] of [['Официальная карточка',product.enrichment?.source_url],...(product.documents || []).map(doc=>[doc.name || 'Документ',doc.url])]) {
    const href=safeLink(url); if(!href)continue;
    const a=document.createElement('a');a.href=href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=title;details.append(a);
  }
  return node;
}
loadSources();
