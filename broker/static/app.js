// Notebook shell — sidebar + same-tab notebook workspace.
// Notebooks open in keep-alive iframes (no new tab); the address bar updates to
// /n/<uuid> via history. Iframes load the proxied, same-origin /nb/<uuid>/ URL.

const THEMES = [
  { id: 'default-dark', label: 'Default · Dark', nb: 'Nexalytica Default Dark' },
  { id: 'default-light', label: 'Default · Light', nb: 'Nexalytica Default Light' },
  { id: 'violet-dark', label: 'Violet · Dark', nb: 'Nexalytica Violet Dark' },
  { id: 'violet-light', label: 'Violet · Light', nb: 'Nexalytica Violet Light' },
  { id: 'sky-dark', label: 'Sky · Dark', nb: 'Nexalytica Sky Dark' },
  { id: 'sky-light', label: 'Sky · Light', nb: 'Nexalytica Sky Light' },
  { id: 'monochrome-dark', label: 'Monochrome · Dark', nb: 'Nexalytica Monochrome Dark' },
  { id: 'monochrome-light', label: 'Monochrome · Light', nb: 'Nexalytica Monochrome Light' }
];

const els = {
  list: document.getElementById('list'), frames: document.getElementById('frames'),
  empty: document.getElementById('empty'), theme: document.getElementById('theme'),
  email: document.getElementById('email'), newBtn: document.getElementById('new-btn'),
  search: document.getElementById('search'), logout: document.getElementById('logout'),
  ctx: document.getElementById('ctx-menu')
};
let notebooks = [], activeId = null, filter = '', ctxTarget = null, counter = 0;

const themeId = () => localStorage.getItem('nx-theme') || 'default-dark';
const nbThemeName = () => (THEMES.find(t => t.id === themeId()) || THEMES[0]).nb;
const find = id => notebooks.find(n => n.id === id);
const escapeHtml = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, method = 'GET', body) {
  const res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.statusText); }
  return res.status === 204 ? null : res.json();
}

function applyTheme(id) { document.documentElement.setAttribute('data-nx', id); localStorage.setItem('nx-theme', id); els.theme.value = id; }

function ensureFrame(n) {
  let f = document.getElementById(`f-${n.id}`);
  if (!f) { f = document.createElement('iframe'); f.id = `f-${n.id}`; f.src = n.url; els.frames.appendChild(f); }
  else if (f.src !== location.origin + n.url && f.getAttribute('src') !== n.url) { f.src = n.url; }
  return f;
}
function showActive() {
  for (const f of els.frames.querySelectorAll('iframe')) f.classList.remove('active');
  const n = find(activeId), running = n && n.running;
  if (running) ensureFrame(n).classList.add('active');
  els.empty.classList.toggle('hidden', !!running);
  render();
}
function routeTo(id) {
  const path = id ? `/n/${id}` : '/';
  if (location.pathname !== path) history.pushState({ id }, '', path);
}

async function openNotebook(id, { push = true } = {}) {
  const n = find(id); if (!n) return;
  if (!n.running) Object.assign(n, await api(`/api/notebooks/${id}/open`, 'POST', { theme: nbThemeName() }));
  activeId = id; if (push) routeTo(id); showActive();
}
async function newNotebook() {
  counter += 1;
  const n = await api('/api/notebooks', 'POST', { name: `Notebook ${counter}`, theme: nbThemeName() });
  notebooks.push(n); await openNotebook(n.id);
}
async function renameNotebook(id) {
  const n = find(id), name = window.prompt('Rename notebook', n.name);
  if (!name || name === n.name) return;
  Object.assign(n, await api(`/api/notebooks/${id}`, 'PATCH', { name })); render();
}
async function closeNotebook(id) {
  const n = find(id); Object.assign(n, await api(`/api/notebooks/${id}/close`, 'POST'));
  const f = document.getElementById(`f-${id}`); if (f) f.remove();
  if (activeId === id) { activeId = null; routeTo(null); }
  showActive();
}
async function deleteNotebook(id) {
  const n = find(id); if (!window.confirm(`Delete "${n.name}"? Files are removed permanently.`)) return;
  await api(`/api/notebooks/${id}`, 'DELETE');
  const f = document.getElementById(`f-${id}`); if (f) f.remove();
  notebooks = notebooks.filter(x => x.id !== id);
  if (activeId === id) { activeId = null; routeTo(null); }
  showActive();
}

function openMenu(id, x, y) {
  ctxTarget = id; els.ctx.hidden = false;
  const w = els.ctx.offsetWidth, h = els.ctx.offsetHeight;
  els.ctx.style.left = Math.min(x, innerWidth - w - 8) + 'px';
  els.ctx.style.top = Math.min(y, innerHeight - h - 8) + 'px';
}
function closeMenu() { els.ctx.hidden = true; ctxTarget = null; }
els.ctx.addEventListener('click', async e => {
  const act = e.target.getAttribute('data-act'); if (!act || !ctxTarget) return;
  const id = ctxTarget; closeMenu();
  try { if (act === 'open') await openNotebook(id); else if (act === 'rename') await renameNotebook(id); else if (act === 'close') await closeNotebook(id); else if (act === 'delete') await deleteNotebook(id); }
  catch (err) { alert('Action failed: ' + err.message); }
});
document.addEventListener('click', e => { if (!els.ctx.hidden && !els.ctx.contains(e.target)) closeMenu(); });

function render() {
  const q = filter.trim().toLowerCase();
  els.list.innerHTML = '';
  for (const n of notebooks) {
    if (q && !n.name.toLowerCase().includes(q)) continue;
    const row = document.createElement('div');
    row.className = `item ${n.running ? 'running' : ''} ${n.id === activeId ? 'active' : ''}`;
    row.onclick = e => { if (!e.target.closest('.kebab')) openNotebook(n.id).catch(err => alert(err.message)); };
    row.innerHTML = `<span class="dot"></span><span class="name">${escapeHtml(n.name)}</span><button class="kebab" title="More">&#8942;</button>`;
    row.querySelector('.kebab').onclick = e => { e.stopPropagation(); const r = e.target.getBoundingClientRect(); openMenu(n.id, r.right - 4, r.bottom + 4); };
    els.list.appendChild(row);
  }
}

function initThemes() {
  for (const t of THEMES) { const o = document.createElement('option'); o.value = t.id; o.textContent = t.label; els.theme.appendChild(o); }
  applyTheme(themeId());
  els.theme.onchange = async e => {
    applyTheme(e.target.value);
    for (const n of notebooks.filter(x => x.running)) {
      try { await api(`/api/notebooks/${n.id}/open`, 'POST', { theme: nbThemeName() }); } catch {}
      const f = document.getElementById(`f-${n.id}`); if (f) f.src = n.url;
    }
  };
}
window.addEventListener('popstate', () => {
  const m = location.pathname.match(/^\/n\/([0-9a-f]+)/);
  if (m && find(m[1])) openNotebook(m[1], { push: false }); else { activeId = null; showActive(); }
});

async function init() {
  initThemes();
  els.newBtn.onclick = () => newNotebook().catch(err => alert('Launch failed: ' + err.message));
  els.search.oninput = e => { filter = e.target.value; render(); };
  els.logout.onclick = async () => { await api('/api/auth/logout', 'POST').catch(() => {}); location.href = '/login'; };
  try {
    els.email.textContent = (await api('/api/me')).email;
    notebooks = await api('/api/notebooks'); counter = notebooks.length;
    render();
    const m = location.pathname.match(/^\/n\/([0-9a-f]+)/);
    if (m && find(m[1])) await openNotebook(m[1], { push: false });
  } catch {}
}
init();
