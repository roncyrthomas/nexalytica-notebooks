// Dashboard — list/create/rename/delete notebooks; open navigates to /e/<id>.
const els = {
  list: document.getElementById('list'),
  email: document.getElementById('email'),
  newBtn: document.getElementById('new-btn'),
  search: document.getElementById('search'),
  logout: document.getElementById('logout'),
  ctx: document.getElementById('ctx-menu'),
};
let notebooks = [], filter = '', ctxTarget = null, counter = 0;
const find = (id) => notebooks.find((n) => n.id === id);
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, method = 'GET', body) {
  const res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.statusText); }
  return res.status === 204 ? null : res.json();
}

const openNotebook = (id) => { location.href = `/e/${id}`; };

async function newNotebook() {
  counter += 1;
  const n = await api('/api/notebooks', 'POST', { name: `Notebook ${counter}`, theme: 'Nexalytica Default Dark' });
  notebooks.push(n); openNotebook(n.id);
}
async function renameNotebook(id) {
  const n = find(id), name = window.prompt('Rename notebook', n.name);
  if (!name || name === n.name) return;
  Object.assign(n, await api(`/api/notebooks/${id}`, 'PATCH', { name })); render();
}
async function deleteNotebook(id) {
  const n = find(id); if (!window.confirm(`Delete "${n.name}"?`)) return;
  await api(`/api/notebooks/${id}`, 'DELETE');
  notebooks = notebooks.filter((x) => x.id !== id); render();
}

function openMenu(id, x, y) {
  ctxTarget = id; els.ctx.hidden = false;
  const w = els.ctx.offsetWidth, h = els.ctx.offsetHeight;
  els.ctx.style.left = Math.min(x, innerWidth - w - 8) + 'px';
  els.ctx.style.top = Math.min(y, innerHeight - h - 8) + 'px';
}
function closeMenu() { els.ctx.hidden = true; ctxTarget = null; }
els.ctx.addEventListener('click', async (e) => {
  const act = e.target.getAttribute('data-act'); if (!act || !ctxTarget) return;
  const id = ctxTarget; closeMenu();
  try { if (act === 'open') openNotebook(id); else if (act === 'rename') await renameNotebook(id); else if (act === 'delete') await deleteNotebook(id); }
  catch (err) { alert('Action failed: ' + err.message); }
});
document.addEventListener('click', (e) => { if (!els.ctx.hidden && !els.ctx.contains(e.target)) closeMenu(); });

function render() {
  const q = filter.trim().toLowerCase();
  els.list.innerHTML = '';
  for (const n of notebooks) {
    if (q && !n.name.toLowerCase().includes(q)) continue;
    const row = document.createElement('div');
    row.className = 'item';
    row.onclick = (e) => { if (!e.target.closest('.kebab')) openNotebook(n.id); };
    row.innerHTML = `<span class="dot"></span><span class="name">${escapeHtml(n.name)}</span><button class="kebab" title="More">&#8942;</button>`;
    row.querySelector('.kebab').onclick = (e) => { e.stopPropagation(); const r = e.target.getBoundingClientRect(); openMenu(n.id, r.right - 4, r.bottom + 4); };
    els.list.appendChild(row);
  }
}

async function init() {
  els.newBtn.onclick = () => newNotebook().catch((err) => alert('Launch failed: ' + err.message));
  els.search.oninput = (e) => { filter = e.target.value; render(); };
  els.logout.onclick = async () => { await api('/api/auth/logout', 'POST').catch(() => {}); location.href = '/login'; };
  try {
    els.email.textContent = (await api('/api/me')).email;
    notebooks = await api('/api/notebooks'); counter = notebooks.length;
    render();
  } catch (e) {}
}
init();
