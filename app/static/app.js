document.querySelectorAll('[data-account]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('username').value = button.dataset.account;
  document.getElementById('password').value = 'Campus@2026';
}));
document.getElementById('toggle-password')?.addEventListener('click', event => {
  const input = document.getElementById('password');
  const showing = input.type === 'password';
  input.type = showing ? 'text' : 'password';
  event.currentTarget.textContent = showing ? '隐藏' : '显示';
  event.currentTarget.setAttribute('aria-label', showing ? '隐藏密码' : '显示密码');
});
document.getElementById('file')?.addEventListener('change', event => {
  document.getElementById('file-label').textContent = event.target.files[0]?.name || '选择一份教学材料';
});
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const materialList = document.getElementById('material-list');
const materialCount = document.getElementById('material-count');
const materialSearch = document.getElementById('material-search');
const renderMaterials = materials => {
  if (!materialList || !materialCount) return;
  materialCount.textContent = materials.length;
  if (!materials.length) {
    materialList.innerHTML = '<div class="empty-state"><h3>没有匹配材料</h3><p>换个关键词再试一次。</p></div>';
    return;
  }
  materialList.innerHTML = materials.map(item => {
    const type = item.original_name.toLowerCase().endsWith('.md') ? 'MD' : 'TXT';
    const created = (item.created_at || '').slice(0, 16);
    return `<article class="material-row"><span class="file-icon">${type}</span><div class="material-info"><a href="/materials/${item.id}">${escapeHtml(item.title)}</a><p>${escapeHtml(item.uploader)} <span>·</span> ${escapeHtml(created)} UTC <span>·</span> ${item.size_bytes} B</p></div><span class="ingested">已入库</span><a class="open-link" href="/materials/${item.id}" aria-label="阅读${escapeHtml(item.title)}">↗</a></article>`;
  }).join('');
};
const refreshMaterials = async () => {
  if (!materialList) return;
  const params = new URLSearchParams();
  const query = materialSearch?.value.trim();
  if (query) params.set('q', query);
  const response = await fetch(`/api/materials${params.toString() ? `?${params}` : ''}`, {headers:{'Accept':'application/json'}});
  if (!response.ok) return;
  const data = await response.json();
  renderMaterials(data.materials || []);
};
refreshMaterials();
materialSearch?.addEventListener('input', () => {
  clearTimeout(materialSearch._timer);
  materialSearch._timer = setTimeout(refreshMaterials, 250);
});
document.getElementById('upload-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form=event.currentTarget, button=form.querySelector('[type=submit]'), output=document.getElementById('upload-result');
  button.disabled=true; output.textContent='正在解析并入库…';
  try {
    const response=await fetch(form.action,{method:'POST',body:new FormData(form)});
    const data=await response.json();
    if(!response.ok) throw new Error(data.error || '上传失败');
    location.assign('/materials?uploaded=1');
  } catch(error) { output.textContent=error.message; button.disabled=false; }
});
document.querySelectorAll('.delete-form').forEach(form => form.addEventListener('submit',async event => {
  event.preventDefault();
  if(!confirm('确定删除这份材料及其知识库内容吗？'))return;
  const button=form.querySelector('button');button.disabled=true;
  try {
    const response=await fetch(form.action,{method:'POST',body:new FormData(form)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error || '删除失败');
    location.assign('/materials?deleted=1');
  }catch(error){alert(error.message);button.disabled=false;}
}));
