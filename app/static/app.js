const TOKEN_KEY = 'campusclaw_access_token';
const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY) || '',
  set: token => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};
const escapeHtml = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let authRedirecting = false;
const clearAuthStorage = () => {
  tokenStore.clear();
};
const logoutAndRedirect = async () => {
  if (authRedirecting) return;
  authRedirecting = true;
  const token = tokenStore.get();
  clearAuthStorage();
  const headers = new Headers({'Accept': 'application/json'});
  if (token) headers.set('Authorization', `Bearer ${token}`);
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers,
      credentials: 'same-origin',
      keepalive: true,
    });
  } catch (error) {
    // Network errors should not trap the user in a stale mixed auth state.
  } finally {
    location.replace('/login');
  }
};
const authHeaders = headers => {
  const token = tokenStore.get();
  if (!token) {
    logoutAndRedirect();
    throw new Error('请重新登录');
  }
  const result = new Headers(headers || {});
  result.set('Authorization', `Bearer ${token}`);
  return result;
};
const apiFetch = async (url, options = {}) => {
  const response = await fetch(url, {...options, headers: authHeaders(options.headers)});
  if (response.status === 401) {
    logoutAndRedirect();
    throw new Error('登录已过期，请重新登录');
  }
  return response;
};

document.querySelectorAll('[data-account]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('username').value = button.dataset.account;
  document.getElementById('password').value = 'Campus@2026';
}));
document.getElementById('token-login-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  tokenStore.clear();
  const form = event.currentTarget;
  const button = form.querySelector('[type=submit]');
  const output = document.getElementById('login-result');
  button.disabled = true;
  if (output) output.hidden = true;
  try {
    const response = await fetch('/api/auth/token', {
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      body: JSON.stringify({
        username: form.username.value,
        password: form.password.value,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '登录失败');
    tokenStore.set(data.access_token);
    location.assign('/materials');
  } catch (error) {
    if (output) {
      output.textContent = error.message;
      output.hidden = false;
    }
    button.disabled = false;
  }
});
document.getElementById('toggle-password')?.addEventListener('click', event => {
  const input = document.getElementById('password');
  const showing = input.type === 'password';
  input.type = showing ? 'text' : 'password';
  event.currentTarget.textContent = showing ? '隐藏' : '显示';
  event.currentTarget.setAttribute('aria-label', showing ? '隐藏密码' : '显示密码');
});
document.getElementById('logout-form')?.addEventListener('submit', event => {
  event.preventDefault();
  logoutAndRedirect();
});
document.getElementById('file')?.addEventListener('change', event => {
  document.getElementById('file-label').textContent = event.target.files[0]?.name || '选择一份教学材料';
});
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
  const response = await apiFetch(`/api/materials${params.toString() ? `?${params}` : ''}`, {headers:{'Accept':'application/json'}});
  if (!response.ok) return;
  const data = await response.json();
  renderMaterials(data.materials || []);
};
refreshMaterials().catch(() => {});
materialSearch?.addEventListener('input', () => {
  clearTimeout(materialSearch._timer);
  materialSearch._timer = setTimeout(() => refreshMaterials().catch(() => {}), 250);
});
document.getElementById('upload-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form=event.currentTarget, button=form.querySelector('[type=submit]'), output=document.getElementById('upload-result');
  button.disabled=true; output.textContent='正在解析并入库…';
  try {
    const response=await apiFetch(form.action,{method:'POST',body:new FormData(form)});
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
    const response=await apiFetch(form.action,{method:'POST',body:new FormData(form)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error || '删除失败');
    location.assign('/materials?deleted=1');
  }catch(error){alert(error.message);button.disabled=false;}
}));
document.querySelectorAll('.download-link').forEach(link => link.addEventListener('click', async event => {
  event.preventDefault();
  const button = event.currentTarget;
  try {
    const response = await apiFetch(button.href, {headers: {'Accept': 'application/octet-stream'}});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || '下载失败');
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = button.dataset.filename || 'material.txt';
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (error) {
    alert(error.message);
  }
}));

const assistantForm = document.getElementById('assistant-form');
const assistantAnswer = document.getElementById('assistant-answer');
const assistantStatus = document.getElementById('assistant-status');
const assistantCitations = document.getElementById('assistant-citations');
let currentConversationId = null;
const renderCitations = citations => {
  if (!assistantCitations) return;
  if (!citations || !citations.length) {
    assistantCitations.className = 'empty-citations';
    assistantCitations.textContent = '暂无引用';
    return;
  }
  assistantCitations.className = '';
  assistantCitations.innerHTML = citations.map(item => `<article class="citation-card"><strong>${escapeHtml(item.citation_id)} ${escapeHtml(item.material_title)}</strong><small>切片 ${item.chunk_index} · 字符 ${item.start_offset}-${item.end_offset}</small><p>${escapeHtml(item.excerpt)}</p><a href="/materials/${item.material_id}">打开对应材料</a></article>`).join('');
};
const handleSseBlock = block => {
  const eventLine = block.split('\n').find(line => line.startsWith('event: '));
  const dataLine = block.split('\n').find(line => line.startsWith('data: '));
  if (!eventLine || !dataLine) return;
  const event = eventLine.slice(7).trim();
  const data = JSON.parse(dataLine.slice(6));
  if (event === 'meta') {
    currentConversationId = data.conversation_id || currentConversationId;
    if (assistantStatus) assistantStatus.textContent = data.retrieval?.degraded ? '向量检索不可用，已按可用证据处理。' : '';
  } else if (event === 'delta') {
    assistantAnswer.textContent += data.text || '';
  } else if (event === 'citations') {
    renderCitations(data.citations || []);
  } else if (event === 'tool_call') {
    if (assistantStatus) assistantStatus.textContent = `工具 ${data.tool_ref}：${data.status}`;
  } else if (event === 'error') {
    if (assistantStatus) assistantStatus.textContent = data.message || 'AI 回答暂不可用';
  }
};
assistantForm?.addEventListener('submit', async event => {
  event.preventDefault();
  const question = document.getElementById('assistant-question').value.trim();
  if (!question) return;
  const button = assistantForm.querySelector('button');
  button.disabled = true;
  assistantAnswer.textContent = '';
  renderCitations([]);
  if (assistantStatus) assistantStatus.textContent = '正在检索本班知识库…';
  try {
    const response = await apiFetch('/api/assistant/ask', {
      method: 'POST',
      headers: {'Accept': 'text/event-stream', 'Content-Type': 'application/json'},
      body: JSON.stringify({question, conversation_id: currentConversationId, app_id: Number(document.getElementById('assistant-app-select')?.value)}),
    });
    if (!response.ok || !response.body) throw new Error('问答请求失败');
    if (assistantStatus) assistantStatus.textContent = '';
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop();
      blocks.forEach(handleSseBlock);
    }
    if (buffer.trim()) handleSseBlock(buffer);
  } catch (error) {
    if (assistantStatus) assistantStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
const promptBox = document.getElementById('assistant-prompt');
const settingsStatus = document.getElementById('assistant-settings-status');
const appSelect = document.getElementById('assistant-app-select');
const templateSelect = document.getElementById('assistant-template-select');
const skillList = document.getElementById('assistant-skill-list');
let assistantApps = [];
let promptTemplates = [];
let assistantSkills = [];
let currentApp = null;
let currentAppSkillIds = new Set();
let selectedSkillId = null;
let mcpServers = [];
let mcpToolsByServer = new Map();
const mcpBusyServerIds = new Set();
const responseJson = async (response, fallback) => {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || fallback);
  return data;
};
const renderSkillCards = () => {
  if (!skillList) return;
  skillList.innerHTML = assistantSkills.map(item => {
    const selected = item.id === selectedSkillId ? ' active' : '';
    const bound = currentAppSkillIds.has(item.id);
    return `<button type="button" class="management-item skill-card${selected}" data-skill-id="${item.id}" aria-pressed="${item.id === selectedSkillId}"><span class="skill-badges"><span class="skill-badge${item.enabled ? '' : ' off'}">${item.enabled ? '启用' : '禁用'}</span><span class="skill-badge${bound ? '' : ' off'}">${bound ? '当前应用已绑定' : '未绑定'}</span></span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.source_type)} · ${escapeHtml(item.trigger_keywords || '无触发词')}</small></button>`;
  }).join('');
};
const allMcpTools = () => mcpServers.flatMap(server =>
  (mcpToolsByServer.get(server.id) || []).map(tool => ({...tool, server, tool_ref:`${tool.tool_name}@${server.name}`})));
const renderSkillToolBindings = skill => {
  const container = document.getElementById('assistant-skill-tools');
  if (!container || !skill) return;
  const selected = new Set(skill.tool_refs || []);
  const available = allMcpTools().filter(item => item.server.connection_status === 'connected');
  const options = [...available];
  for (const ref of selected) {
    if (!options.some(item => item.tool_ref === ref)) {
      options.push({tool_ref:ref,tool_name:ref.split('@')[0],description:'当前服务器或工具不可用',server:{name:ref.split('@')[1] || '',connection_status:'disconnected'},unavailable:true});
    }
  }
  container.innerHTML = options.length ? options.map(item => `<label class="tool-binding-option"><input type="checkbox" value="${escapeHtml(item.tool_ref)}" ${selected.has(item.tool_ref) ? 'checked' : ''} ${item.unavailable ? 'disabled' : ''}><span><strong>${escapeHtml(item.tool_name)}</strong><small>${escapeHtml(item.server.name)} · ${escapeHtml(item.description || '无说明')}${item.unavailable ? ' · 当前不可用' : ''}</small></span></label>`).join('') : '<p class="muted">请先连接 MCP 服务器并发现工具。</p>';
};
const renderMcpServers = () => {
  const serverList = document.getElementById('mcp-server-list');
  if (!serverList) return;
  serverList.innerHTML = mcpServers.length ? mcpServers.map(server => {
    const tools = mcpToolsByServer.get(server.id) || [];
    const busy = mcpBusyServerIds.has(server.id);
    const connectLabel = server.connection_status === 'connected' ? '重新连接并发现工具' : '连接并发现工具';
    const toolHtml = tools.length ? tools.map(tool => `<details class="mcp-tool"><summary><strong>${escapeHtml(tool.tool_name)}</strong></summary><p>${escapeHtml(tool.description || '无说明')}</p><pre>${escapeHtml(JSON.stringify(tool.input_schema, null, 2))}</pre></details>`).join('') : '<p class="muted">尚未发现工具。</p>';
    return `<article class="management-item mcp-server-card" data-mcp-server-id="${server.id}"><div class="mcp-server-heading"><strong>${escapeHtml(server.name)}</strong><span class="mcp-status ${escapeHtml(server.connection_status)}">${escapeHtml(server.connection_status)}</span></div><div class="mcp-server-meta">${escapeHtml(server.endpoint_url)} · 令牌环境变量 ${escapeHtml(server.token_env_key)}</div>${server.last_error ? `<p class="mcp-server-error">${escapeHtml(server.last_error)}</p>` : ''}<div class="mcp-server-actions"><button type="button" class="button" data-mcp-action="connect" ${busy ? 'disabled' : ''}>${busy ? '连接中…' : connectLabel}</button>${server.connection_status === 'connected' ? `<button type="button" class="button" data-mcp-action="disconnect" ${busy ? 'disabled' : ''}>断开</button>` : ''}</div><div class="mcp-tool-list">${toolHtml}</div></article>`;
  }).join('') : '<p class="muted">尚未登记 MCP 服务器</p>';
};
const refreshMcpServers = async providedServers => {
  if (providedServers) {
    mcpServers = providedServers;
  } else {
    const data = await responseJson(await apiFetch('/api/mcp/servers', {headers:{'Accept':'application/json'}}), 'MCP 服务器列表加载失败');
    mcpServers = data.servers || [];
  }
  const entries = await Promise.all(mcpServers.map(async server => {
    const data = await responseJson(await apiFetch(`/api/mcp/servers/${server.id}/tools`, {headers:{'Accept':'application/json'}}), `MCP 工具列表加载失败：${server.name}`);
    return [server.id,data.tools || []];
  }));
  mcpToolsByServer = new Map(entries);
  renderMcpServers();
  if (selectedSkillId) showSkillDetail(selectedSkillId);
};
const showSkillDetail = skillId => {
  const detail = document.getElementById('assistant-skill-detail');
  const skill = assistantSkills.find(item => item.id === Number(skillId));
  if (!detail || !skill) return;
  selectedSkillId = skill.id;
  detail.hidden = false;
  document.getElementById('assistant-skill-detail-name').textContent = skill.name;
  document.getElementById('assistant-skill-detail-source').textContent = `${skill.source_type} · 优先级 ${skill.priority}`;
  document.getElementById('assistant-skill-detail-key').textContent = skill.skill_key;
  document.getElementById('assistant-skill-detail-description').textContent = skill.description || '暂无说明';
  document.getElementById('assistant-skill-enabled').checked = Boolean(skill.enabled);
  document.getElementById('assistant-skill-keywords').value = skill.trigger_keywords || '';
  document.getElementById('assistant-skill-content').value = skill.content || '';
  document.getElementById('assistant-skill-bound').checked = currentAppSkillIds.has(skill.id);
  renderSkillToolBindings(skill);
  document.getElementById('assistant-skill-status').textContent = '';
  renderSkillCards();
};
const loadCurrentApp = async () => {
  if (!appSelect?.value) return;
  const response = await apiFetch(`/api/assistant/apps/${appSelect.value}`, {headers:{'Accept':'application/json'}});
  const data = await responseJson(response, '应用配置加载失败'); currentApp = data.app;
  currentAppSkillIds = new Set((data.skills || []).map(item => item.id));
  document.getElementById('assistant-app-description').textContent = currentApp.description;
  if (promptBox) promptBox.value = currentApp.system_prompt_template || '';
  const temperature = document.getElementById('assistant-temperature'); if (temperature) temperature.value = currentApp.temperature;
  const topK = document.getElementById('assistant-top-k'); if (topK) topK.value = currentApp.top_k;
  const retrieval = document.getElementById('assistant-retrieval'); if (retrieval) retrieval.checked = Boolean(currentApp.retrieval_enabled);
  const bound = document.getElementById('assistant-bound-skills'); if (bound) bound.textContent = `绑定 Skill：${data.skills.map(item => item.name).join('、') || '无'}`;
  if (templateSelect) templateSelect.value = '';
  renderSkillCards();
  if (selectedSkillId) showSkillDetail(selectedSkillId);
};
const loadAssistantSettings = async () => {
  if (!appSelect) return;
  const appsData = await responseJson(
    await apiFetch('/api/assistant/apps', {headers:{'Accept':'application/json'}}), '应用列表加载失败');
  assistantApps = appsData.apps || [];
  appSelect.innerHTML = assistantApps.map(item => `<option value="${item.id}">${escapeHtml(item.name)} · ${item.retrieval_enabled ? '知识库' : '通用'}</option>`).join('');
  if (promptBox) {
    const [templatesData, skillsData, serversData] = await Promise.all([
      apiFetch('/api/assistant/prompt-templates', {headers:{'Accept':'application/json'}}).then(response => responseJson(response, '模板库加载失败')),
      apiFetch('/api/assistant/skills', {headers:{'Accept':'application/json'}}).then(response => responseJson(response, 'Skill 列表加载失败')),
      apiFetch('/api/mcp/servers', {headers:{'Accept':'application/json'}}).then(response => responseJson(response, 'MCP 服务器列表加载失败')),
    ]);
    promptTemplates = templatesData.templates || [];
    assistantSkills = skillsData.items || [];
    if (templateSelect) templateSelect.innerHTML = '<option value="">不应用模板</option>' + promptTemplates.map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join('');
    await refreshMcpServers(serversData.servers || []);
  }
  await loadCurrentApp();
};
if (appSelect) {
  loadAssistantSettings().catch(error => {
    const output = settingsStatus || document.getElementById('management-status');
    if (output) output.textContent = error.message;
  });
}
appSelect?.addEventListener('change', () => { currentConversationId = null; selectedSkillId = null; document.getElementById('assistant-skill-detail')?.setAttribute('hidden',''); loadCurrentApp().catch(error => { if (settingsStatus) settingsStatus.textContent = error.message; }); });
templateSelect?.addEventListener('change', () => {
  if (!promptBox || !currentApp) return;
  if (!templateSelect.value) {
    promptBox.value = currentApp.system_prompt_template || '';
    if (settingsStatus) settingsStatus.textContent = '已恢复当前应用最近保存的 Prompt；尚未提交新修改。';
    return;
  }
  const template = promptTemplates.find(item => item.id === Number(templateSelect.value));
  if (!template) return;
  promptBox.value = template.content;
  if (settingsStatus) settingsStatus.textContent = `已将“${template.name}”复制到编辑区；点击保存后才会生效。`;
});
document.getElementById('save-assistant-settings')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  if (button.disabled) return;
  button.disabled = true;
  if (settingsStatus) settingsStatus.textContent = '正在保存…';
  try {
    const response = await apiFetch(`/api/assistant/apps/${appSelect.value}`, {
      method: 'PUT',
      headers: {'Accept':'application/json','Content-Type':'application/json'},
      body: JSON.stringify({system_prompt_template: promptBox.value, temperature: Number(document.getElementById('assistant-temperature').value), top_k: Number(document.getElementById('assistant-top-k').value), retrieval_enabled: document.getElementById('assistant-retrieval').checked}),
    });
    await responseJson(response, '保存失败');
    await loadCurrentApp();
    if (settingsStatus) settingsStatus.textContent = '已保存，下一轮提问生效。';
  } catch (error) {
    if (settingsStatus) settingsStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.getElementById('assistant-skill-list')?.addEventListener('click', event => {
  const card = event.target.closest('[data-skill-id]');
  if (card) showSkillDetail(card.dataset.skillId);
});
document.getElementById('save-skill-settings')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  if (button.disabled || !selectedSkillId || !currentApp) return;
  button.disabled = true;
  const status = document.getElementById('assistant-skill-status');
  if (status) status.textContent = '正在保存 Skill 设置…';
  try {
    const response = await apiFetch(`/api/assistant/skills/${selectedSkillId}`, {
      method:'PUT', headers:{'Accept':'application/json','Content-Type':'application/json'},
      body:JSON.stringify({
        enabled:document.getElementById('assistant-skill-enabled').checked,
        trigger_keywords:document.getElementById('assistant-skill-keywords').value,
        content:document.getElementById('assistant-skill-content').value,
      }),
    });
    await responseJson(response, 'Skill 保存失败');
    const bound = document.getElementById('assistant-skill-bound').checked;
    const nextIds = new Set(currentAppSkillIds);
    if (bound) nextIds.add(selectedSkillId); else nextIds.delete(selectedSkillId);
    const bindingResponse = await apiFetch(`/api/assistant/apps/${currentApp.id}/skills`, {
      method:'PUT', headers:{'Accept':'application/json','Content-Type':'application/json'},
      body:JSON.stringify({skill_ids:[...nextIds]}),
    });
    await responseJson(bindingResponse, 'Skill 绑定保存失败');
    const currentSkill = assistantSkills.find(item => item.id === selectedSkillId);
    const nextToolRefs = [...document.querySelectorAll('#assistant-skill-tools input[type=checkbox]:checked')].map(input => input.value).sort();
    const currentToolRefs = [...(currentSkill?.tool_refs || [])].sort();
    if (JSON.stringify(nextToolRefs) !== JSON.stringify(currentToolRefs)) {
      const toolsResponse = await apiFetch(`/api/assistant/skills/${selectedSkillId}/tools`, {
        method:'PUT',headers:{'Accept':'application/json','Content-Type':'application/json'},body:JSON.stringify({tool_refs:nextToolRefs}),
      });
      await responseJson(toolsResponse, 'Skill 工具绑定保存失败');
    }
    const skillsData = await responseJson(
      await apiFetch('/api/assistant/skills', {headers:{'Accept':'application/json'}}), 'Skill 列表刷新失败');
    assistantSkills = skillsData.items || [];
    await loadCurrentApp();
    showSkillDetail(selectedSkillId);
    if (status) status.textContent = 'Skill 设置已保存，下一轮路由立即生效。';
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.getElementById('skill-upload-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type=submit]');
  const status = document.getElementById('management-status');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const response = await apiFetch('/api/assistant/skills/upload', {method:'POST', body:new FormData(form)});
    await responseJson(response, 'Skill 上传失败');
    if (status) status.textContent = 'Skill 已上传；默认不绑定到应用。';
    await loadAssistantSettings();
    form.reset();
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.getElementById('mcp-server-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type=submit]');
  const status = document.getElementById('management-status');
  if (button.disabled) return;
  button.disabled = true;
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    const response = await apiFetch('/api/mcp/servers', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    await responseJson(response, 'MCP 服务器登记失败');
    if (status) status.textContent = 'MCP 服务器已登记；请点击“连接并发现工具”。';
    await refreshMcpServers();
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.getElementById('mcp-server-list')?.addEventListener('click', async event => {
  const button = event.target.closest('[data-mcp-action]');
  const card = event.target.closest('[data-mcp-server-id]');
  if (!button || !card || button.disabled) return;
  const serverId = Number(card.dataset.mcpServerId);
  const action = button.dataset.mcpAction;
  const status = document.getElementById('management-status');
  if (!serverId || !['connect','disconnect'].includes(action) || mcpBusyServerIds.has(serverId)) return;
  mcpBusyServerIds.add(serverId);
  renderMcpServers();
  if (status) status.textContent = action === 'connect' ? '正在连接 MCP 服务器并发现工具…' : '正在断开 MCP 服务器…';
  try {
    const response = await apiFetch(`/api/mcp/servers/${serverId}/${action}`, {method:'POST',headers:{'Accept':'application/json'}});
    const data = await responseJson(response, action === 'connect' ? 'MCP 连接失败' : 'MCP 断开失败');
    await refreshMcpServers();
    if (status) status.textContent = action === 'connect' ? `MCP 已连接，发现 ${(data.tools || []).length} 个工具。` : 'MCP 服务器已断开，发现清单已清除。';
  } catch (error) {
    try { await refreshMcpServers(); } catch (_) { /* Keep the original action error. */ }
    const latest = mcpServers.find(item => item.id === serverId);
    if (status) status.textContent = `MCP ${action === 'connect' ? '连接' : '断开'}失败：${latest?.last_error || error.message}`;
  } finally {
    mcpBusyServerIds.delete(serverId);
    renderMcpServers();
  }
});
