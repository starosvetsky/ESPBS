// Source selection and safe product preview. The existing archive flow is reused.
let sourceRegistry = [];
const sourceLabel = id => sourceRegistry.find(x => x.id === id)?.name || id || 'Eltex';
function setSource() {
  const entry = sourceRegistry.find(x => x.id === $('#source').value);
  if (!entry) return;
  $('#start-url').value = entry.default_url;
  $('#source-help').textContent = entry.description;
  $('#enrichment').replaceChildren(...entry.enrichments.map(value => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value === 'eltex' ? 'Eltex — фото, характеристики, документы' : 'Без дополнительного обогащения';
    return option;
  }));
}
async function loadSources() {
  try {
    sourceRegistry = (await api('api/sources')).sources;
    $('#source').replaceChildren(...sourceRegistry.map(entry => {
      const option = document.createElement('option');
      option.value = entry.id; option.textContent = entry.name; return option;
    }));
    $('#source').value = 'olnisa'; setSource(); await loadStorage(); await loadJobs();
  } catch (error) { $('#source-help').textContent = error.message; }
}
$('#source').onchange = setSource;
function safeLink(url) {
  try { const u = new URL(url); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
}
function productPreview(product) {
  const node = document.createElement('div'); node.className = 'product';
  const image = (product.images || []).find(url => {
    try { return new URL(url).origin === 'https://eltex.ru'; } catch { return false; }
  });
  const status = product.enrichment?.status;
  const label = status === 'MATCHED' ? 'Официальные данные подтверждены' : status === 'ERROR' ? 'Ошибка обогащения' : status === 'REVIEW' ? 'Нужно проверить соответствие' : product.quality?.status === 'GOOD' ? 'Проверено' : 'Требует проверки';
  node.innerHTML = `${image ? `<img loading="lazy" src="${escapeHtml(image)}" alt="${escapeHtml(product.name)}">` : '<div class="no-photo">Нет официального фото</div>'}<strong>${escapeHtml(product.name)}</strong><span>${escapeHtml(label)}</span><p>${escapeHtml(product.offer?.price_text || '')} ${escapeHtml(product.offer?.availability || '')}</p><details><summary>Характеристики и источники</summary><p>${escapeHtml(product.description || '')}</p><dl>${Object.entries(product.attributes || {}).map(([key,value])=>`<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(Array.isArray(value)?value.join('; '):value)}</dd>`).join('')}</dl><p>${(product.quality?.issues || []).map(escapeHtml).join('<br>')}</p></details>`;
  const img = node.querySelector('img');
  if (img) img.onerror = () => { const text=document.createElement('div');text.className='no-photo';text.textContent='Фото временно недоступно';img.replaceWith(text); };
  const details = node.querySelector('details');
  for (const [title,url] of [['Магазин / источник',product.source_url],['Официальная карточка',product.enrichment?.source_url],...(product.documents || []).map(doc=>[doc.name || 'Документ',doc.url])]) {
    const href=safeLink(url); if(!href)continue;
    const a=document.createElement('a');a.href=href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=title;details.append(a);
  }
  return node;
}
loadSources();
