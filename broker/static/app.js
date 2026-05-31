// Nexalytica Notebooks - enterprise shell.
// Sidebar = notebook explorer (search, status, context menu). Center = the
// active notebook iframe (kept alive so switching is instant). The theme
// selector restyles the page AND syncs every running notebook's theme.

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
  list: document.getElementById('list'),
  frames: document.getElementById('frames'),
  empty: document.getElementById('empty'),
  theme: document.getElementById('theme'),
  newBtn: document.getElementById('new-btn'),
  search: document.getElementById('search'),
  ctx: document.getElementById('ctx-menu')
};

let notebooks = [];
let activeId = null;
let counter = 0;
let filter = '';
let ctxTarget = null;

const themeId = () => localStorage.getItem('nx-theme') || 'default-dark';
const nbThemeName = () => (THEMES.find(t => t.id === themeId()) || THEMES[0]).nb;
const find = (id) => notebooks.find(n => n.id === id);

async function api(path, method = 'GET', body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) throw new Error(await res.text());
  return res.status === 204 ? null : res.json();
}

/* ---- theming ------------------------------------------------------------ */
function applyPageTheme(id) {
  document.documentElement.setAttribute('data-nx', id);
  localStorage.setItem('nx-theme', id);
  els.theme.value = id;
}
async function onThemeChange(id) {
  applyPageTheme(id);
  const nb = nbThemeName();
  for (const n of notebooks.filter(x => x.status === 'running')) {
    try { await api(`/api/notebooks/${n.id}/open`, 'POST', { theme: nb }); } catch {}
    const f = document.getElementById(`f-${n.id}`);
    if (f) f.src = n.url;
  }
}

/* ---- iframes ------------------------------------------------------------ */
function ensureFrame(n) {
  let f = document.getElementById(`f-${n.id}`);
  if (!f) {
    f = document.createElement('iframe');
    f.id = `f-${n.id}`;
    f.src = n.url;
    els.frames.appendChild(f);
  } else if (f.src !== n.url) {
    f.src = n.url;
  }
  return f;
}
function showActive() {
  for (const f of els.frames.querySelectorAll('iframe')) f.classList.remove('active');
  const n = find(activeId);
  const running = n && n.status === 'running';
  if (running) ensureFrame(n).classList.add('active');
  els.empty.classList.toggle('hidden', !!running);
}

/* ---- actions ------------------------------------------------------------ */
async function newNotebook() {
  counter += 1;
  const n = await api('/api/notebooks', 'POST', { name: `Notebook ${counter}`, theme: nbThemeName() });
  notebooks.push(n);
  activeId = n.id;
  render(); showActive();
}
async function openNotebook(id) {
  const n = find(id);
  if (!n) return;
  if (n.status !== 'running') {
    Object.assign(n, await api(`/api/notebooks/${id}/open`, 'POST', { theme: nbThemeName() }));
  }
  activeId = id;
  render(); showActive();
}
async function closeNotebook(id) {
  const n = find(id);
  Object.assign(n, await api(`/api/notebooks/${id}/close`, 'POST'));
  const f = document.getElementById(`f-${id}`);
  if (f) f.remove();
  render(); showActive();
}
async function renameNotebook(id) {
  const n = find(id);
  const name = window.prompt('Rename notebook', n.name);
  if (!name || name === n.name) return;
  Object.assign(n, await api(`/api/notebooks/${id}`, 'PATCH', { name }));
  render();
}
async function duplicateNotebook(id) {
  const dup = await api(`/api/notebooks/${id}/duplicate`, 'POST');
  notebooks.push(dup);
  render();
}
async function deleteNotebook(id) {
  const n = find(id);
  if (!window.confirm(`Delete "${n.name}"? This removes its files permanently.`)) return;
  await api(`/api/notebooks/${id}`, 'DELETE');
  const f = document.getElementById(`f-${id}`);
  if (f) f.remove();
  notebooks = notebooks.filter(x => x.id !== id);
  if (activeId === id) activeId = null;
  render(); showActive();
}

/* ---- context menu ------------------------------------------------------- */
function openMenu(n, x, y) {
  ctxTarget = n.id;
  const running = n.status === 'running';
  els.ctx.innerHTML =
    `<button data-act="open">Open</button>` +
    (running ? `<button data-act="close">Close session</button>` : '') +
    `<button data-act="rename">Rename</button>` +
    `<button data-act="duplicate">Duplicate</button>` +
    `<div class="sep"></div>` +
    `<button data-act="delete" class="danger">Delete</button>`;
  els.ctx.hidden = false;
  const w = els.ctx.offsetWidth, h = els.ctx.offsetHeight;
  els.ctx.style.left = Math.min(x, window.innerWidth - w - 8) + 'px';
  els.ctx.style.top = Math.min(y, window.innerHeight - h - 8) + 'px';
  document.querySelectorAll('.item').forEach(el => el.classList.remove('menu-open'));
  const row = document.getElementById(`row-${n.id}`);
  if (row) row.classList.add('menu-open');
}
function closeMenu() {
  els.ctx.hidden = true; ctxTarget = null;
  document.querySelectorAll('.item').forEach(el => el.classList.remove('menu-open'));
}
els.ctx.addEventListener('click', async (e) => {
  const act = e.target.getAttribute('data-act');
  if (!act || !ctxTarget) return;
  const id = ctxTarget;
  closeMenu();
  try {
    if (act === 'open') await openNotebook(id);
    else if (act === 'close') await closeNotebook(id);
    else if (act === 'rename') await renameNotebook(id);
    else if (act === 'duplicate') await duplicateNotebook(id);
    else if (act === 'delete') await deleteNotebook(id);
  } catch (err) { alert('Action failed: ' + err.message); }
});
document.addEventListener('click', (e) => {
  if (!els.ctx.hidden && !els.ctx.contains(e.target)) closeMenu();
});

/* ---- render ------------------------------------------------------------- */
function render() {
  const q = filter.trim().toLowerCase();
  els.list.innerHTML = '';
  for (const n of notebooks) {
    if (q && !n.name.toLowerCase().includes(q)) continue;
    const row = document.createElement('div');
    row.id = `row-${n.id}`;
    row.className = `item ${n.status} ${n.id === activeId ? 'active' : ''}`;
    row.onclick = (e) => { if (!e.target.closest('.kebab')) openNotebook(n.id); };
    row.innerHTML =
      `<span class="dot"></span><span class="name">${escapeHtml(n.name)}</span>` +
      `<button class="kebab" title="More">&#8942;</button>`;
    row.querySelector('.kebab').onclick = (e) => {
      e.stopPropagation();
      const r = e.target.getBoundingClientRect();
      openMenu(n, r.right - 4, r.bottom + 4);
    };
    els.list.appendChild(row);
  }
}
function escapeHtml(s) {
  return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ---- init --------------------------------------------------------------- */
function initThemes() {
  for (const t of THEMES) {
    const o = document.createElement('option');
    o.value = t.id; o.textContent = t.label;
    els.theme.appendChild(o);
  }
  applyPageTheme(themeId());
  els.theme.onchange = (e) => onThemeChange(e.target.value);
}
async function init() {
  initThemes();
  els.newBtn.onclick = () => newNotebook().catch(err => alert('Launch failed: ' + err.message));
  els.search.oninput = (e) => { filter = e.target.value; render(); };
  try {
    notebooks = await api('/api/notebooks');
    counter = notebooks.length;
    render();
    const running = notebooks.find(n => n.status === 'running');
    if (running) { activeId = running.id; showActive(); }
  } catch {}
}
init();
