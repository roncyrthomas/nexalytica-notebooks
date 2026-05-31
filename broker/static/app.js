// Nexalytica Notebook - multi-user dashboard.
// Notebooks open FULL-PAGE at their own /nb/<uuid>/ URL (no iframe), in a new
// tab, so several can run concurrently. The theme selector restyles this page
// and is applied to a notebook when it is opened.

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
  grid: document.getElementById('grid'),
  empty: document.getElementById('empty'),
  search: document.getElementById('search'),
  theme: document.getElementById('theme'),
  email: document.getElementById('email'),
  newBtn: document.getElementById('new-btn'),
  logout: document.getElementById('logout'),
  ctx: document.getElementById('ctx-menu')
};

let notebooks = [];
let filter = '';
let ctxTarget = null;
let counter = 0;

const themeId = () => localStorage.getItem('nx-theme') || 'default-dark';
const nbThemeName = () => (THEMES.find(t => t.id === themeId()) || THEMES[0]).nb;
const find = (id) => notebooks.find(n => n.id === id);

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || res.statusText);
  }
  return res.status === 204 ? null : res.json();
}

function applyTheme(id) {
  document.documentElement.setAttribute('data-nx', id);
  localStorage.setItem('nx-theme', id);
  els.theme.value = id;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function render() {
  const q = filter.trim().toLowerCase();
  const shown = notebooks.filter(n => !q || n.name.toLowerCase().includes(q));
  els.grid.innerHTML = '';
  els.empty.hidden = notebooks.length !== 0;
  for (const n of shown) {
    const card = document.createElement('div');
    card.className = `nb-card ${n.running ? 'running' : ''}`;
    card.onclick = (e) => { if (!e.target.closest('.kebab')) openNotebook(n.id); };
    card.innerHTML =
      `<div class="nb-top"><span class="dot"></span>` +
      `<span class="nb-name">${escapeHtml(n.name)}</span>` +
      `<button class="kebab" title="More">&#8942;</button></div>` +
      `<div class="nb-meta">${n.running ? 'Running · click to open' : 'Idle · click to start'}</div>`;
    card.querySelector('.kebab').onclick = (e) => {
      e.stopPropagation();
      const r = e.target.getBoundingClientRect();
      openMenu(n.id, r.right - 4, r.bottom + 4);
    };
    els.grid.appendChild(card);
  }
}

async function newNotebook() {
  counter += 1;
  const n = await api('/api/notebooks', 'POST', { name: `Notebook ${counter}`, theme: nbThemeName() });
  notebooks.push(n);
  render();
  openNotebook(n.id);
}

async function openNotebook(id) {
  const n = find(id);
  if (!n) return;
  const tab = window.open('', '_blank');   // open synchronously to avoid popup block
  if (tab) tab.document.write('Starting notebook…');
  try {
    const updated = await api(`/api/notebooks/${id}/open`, 'POST', { theme: nbThemeName() });
    Object.assign(n, updated);
    render();
    if (tab) tab.location.href = updated.url; else location.href = updated.url;
  } catch (e) {
    if (tab) tab.close();
    alert('Could not open: ' + e.message);
  }
}

async function renameNotebook(id) {
  const n = find(id);
  const name = window.prompt('Rename notebook', n.name);
  if (!name || name === n.name) return;
  Object.assign(n, await api(`/api/notebooks/${id}`, 'PATCH', { name }));
  render();
}

async function closeNotebook(id) {
  const n = find(id);
  Object.assign(n, await api(`/api/notebooks/${id}/close`, 'POST'));
  render();
}

async function deleteNotebook(id) {
  const n = find(id);
  if (!window.confirm(`Delete "${n.name}"? Its files are removed permanently.`)) return;
  await api(`/api/notebooks/${id}`, 'DELETE');
  notebooks = notebooks.filter(x => x.id !== id);
  render();
}

// ---- context menu ----
function openMenu(id, x, y) {
  ctxTarget = id;
  els.ctx.hidden = false;
  const w = els.ctx.offsetWidth, h = els.ctx.offsetHeight;
  els.ctx.style.left = Math.min(x, window.innerWidth - w - 8) + 'px';
  els.ctx.style.top = Math.min(y, window.innerHeight - h - 8) + 'px';
}
function closeMenu() { els.ctx.hidden = true; ctxTarget = null; }
els.ctx.addEventListener('click', async (e) => {
  const act = e.target.getAttribute('data-act');
  if (!act || !ctxTarget) return;
  const id = ctxTarget; closeMenu();
  try {
    if (act === 'open') await openNotebook(id);
    else if (act === 'rename') await renameNotebook(id);
    else if (act === 'close') await closeNotebook(id);
    else if (act === 'delete') await deleteNotebook(id);
  } catch (err) { alert('Action failed: ' + err.message); }
});
document.addEventListener('click', (e) => {
  if (!els.ctx.hidden && !els.ctx.contains(e.target)) closeMenu();
});

// ---- init ----
function initThemes() {
  for (const t of THEMES) {
    const o = document.createElement('option');
    o.value = t.id; o.textContent = t.label; els.theme.appendChild(o);
  }
  applyTheme(themeId());
  els.theme.onchange = (e) => applyTheme(e.target.value);
}

async function init() {
  initThemes();
  els.newBtn.onclick = () => newNotebook().catch(err => alert('Launch failed: ' + err.message));
  els.search.oninput = (e) => { filter = e.target.value; render(); };
  els.logout.onclick = async () => { await api('/api/auth/logout', 'POST').catch(() => {}); location.href = '/login'; };
  try {
    const me = await api('/api/me');
    els.email.textContent = me.email;
    notebooks = await api('/api/notebooks');
    counter = notebooks.length;
    render();
  } catch { /* redirected to login */ }
}
init();
