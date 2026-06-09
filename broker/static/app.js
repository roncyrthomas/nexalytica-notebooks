// app.js — SPA controller: routing, loading overlay, theme, rename, export.
const THEMES = [
  { id: 'default-dark',    label: 'Default · Dark' },
  { id: 'default-light',   label: 'Default · Light' },
  { id: 'violet-dark',     label: 'Violet · Dark' },
  { id: 'violet-light',    label: 'Violet · Light' },
  { id: 'sky-dark',        label: 'Sky · Dark' },
  { id: 'sky-light',       label: 'Sky · Light' },
  { id: 'monochrome-dark', label: 'Monochrome · Dark' },
  { id: 'monochrome-light', label: 'Monochrome · Light' },
];

const els = {
  list:       document.getElementById('list'),
  email:      document.getElementById('email'),
  newBtn:     document.getElementById('new-btn'),
  search:     document.getElementById('search'),
  logout:     document.getElementById('logout'),
  ctx:        document.getElementById('ctx-menu'),
  theme:      document.getElementById('theme'),
  empty:      document.getElementById('empty'),
  loading:    document.getElementById('loading'),
  editorRoot: document.getElementById('editor-root'),
};

let notebooks = [], activeId = null, filter = '', ctxTarget = null, counter = 0;
let activeView = null;   // current NotebookView instance

const find       = (id) => notebooks.find((n) => n.id === id);
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---- api helper ----
async function api(path, method, body) {
  method = method || 'GET';
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
  if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || res.statusText); }
  return res.status === 204 ? null : res.json();
}

// ---- theme ----
function themeId() { return localStorage.getItem('nx-theme') || 'default-dark'; }

function applyTheme(id) {
  document.documentElement.setAttribute('data-nx', id);
  localStorage.setItem('nx-theme', id);
  els.theme.value = id;
}

function initThemes() {
  for (const t of THEMES) {
    const o = document.createElement('option');
    o.value = t.id; o.textContent = t.label;
    els.theme.appendChild(o);
  }
  applyTheme(themeId());
  els.theme.onchange = (e) => applyTheme(e.target.value);
}

// ---- pane visibility ----
function showEmpty() {
  els.empty.hidden   = false;
  els.loading.hidden = true;
  els.editorRoot.classList.remove('active');
}

function showLoading() {
  els.empty.hidden   = true;
  els.loading.hidden = false;
  els.editorRoot.classList.remove('active');
}

function showEditor() {
  els.empty.hidden   = true;
  els.loading.hidden = true;
  els.editorRoot.classList.add('active');
}

// ---- routing ----
async function openNotebook(id, push) {
  if (push === undefined) push = true;
  const n = find(id); if (!n) return;
  // already open: don't remount (would drop the warm kernel + in-memory state)
  if (id === activeId && activeView) { if (push) history.pushState({ id }, '', '/e/' + id); return; }
  if (push) history.pushState({ id }, '', '/e/' + id);
  activeId = id;
  render();
  showLoading();

  // tear down previous view
  if (activeView) { activeView.destroy(); activeView = null; }

  try {
    activeView = window.NotebookView(els.editorRoot, id, {
      onTitle: function (name) {
        // update sidebar item name if server returns a different display name
        if (n) n.name = name;
        render();
      },
      onKernel: function () { /* kernel pill lives inside the view */ },
      onLoaded: function () {
        showEditor();
      },
    });
  } catch (e) {
    showEmpty();            // never leave the shimmer stuck on a synchronous failure
    throw e;
  }

  render();
}

async function newNotebook() {
  counter += 1;
  const n = await api('/api/notebooks', 'POST', { name: 'Notebook ' + counter });
  notebooks.push(n);
  await openNotebook(n.id);
}

// ---- sidebar render ----
function render() {
  const q = filter.trim().toLowerCase();
  els.list.innerHTML = '';
  for (const n of notebooks) {
    if (q && !n.name.toLowerCase().includes(q)) continue;
    const row = document.createElement('div');
    row.className = 'item' + (n.id === activeId ? ' active' : '');
    row.onclick = (e) => { if (!e.target.closest('.kebab')) openNotebook(n.id).catch((err) => alert(err.message)); };
    row.innerHTML =
      '<span class="dot"></span>' +
      '<span class="name">' + escapeHtml(n.name) + '</span>' +
      '<button class="kebab" title="More">&#8942;</button>';
    row.querySelector('.kebab').onclick = (e) => {
      e.stopPropagation();
      const r = e.target.getBoundingClientRect();
      openMenu(n.id, r.right - 4, r.bottom + 4);
    };
    els.list.appendChild(row);
  }
}

// ---- context menu ----
function openMenu(id, x, y) {
  ctxTarget = id;
  els.ctx.hidden = false;
  const w = els.ctx.offsetWidth, h = els.ctx.offsetHeight;
  els.ctx.style.left = Math.min(x, innerWidth  - w - 8) + 'px';
  els.ctx.style.top  = Math.min(y, innerHeight - h - 8) + 'px';
}
function closeMenu() { els.ctx.hidden = true; ctxTarget = null; }

els.ctx.addEventListener('click', async (e) => {
  const act = e.target.getAttribute('data-act'); if (!act || !ctxTarget) return;
  const id = ctxTarget; closeMenu();
  try {
    if (act === 'open') {
      await openNotebook(id);
    } else if (act === 'rename') {
      await renameNotebook(id);
    } else if (act === 'export-ipynb' || act === 'export-py' || act === 'export-html') {
      const fmt = act.replace('export-', '');
      await exportNotebook(id, fmt);
    } else if (act === 'delete') {
      await deleteNotebook(id);
    }
  } catch (err) {
    alert('Action failed: ' + err.message);
  }
});
document.addEventListener('click', (e) => { if (!els.ctx.hidden && !els.ctx.contains(e.target)) closeMenu(); });

async function renameNotebook(id) {
  const n = find(id);
  const name = window.prompt('Rename notebook', n.name);
  if (!name || name === n.name) return;
  Object.assign(n, await api('/api/notebooks/' + id, 'PATCH', { name }));
  // if the active view is this notebook, update its title
  if (id === activeId && activeView && activeView.setName) activeView.setName(n.name);
  render();
}

async function exportNotebook(id, fmt) {
  // if the notebook is open, delegate directly
  if (id === activeId && activeView) {
    activeView.exportAs(fmt);
    return;
  }
  // otherwise open it first, then export once loaded
  await openNotebook(id);
  // exportAs is safe to call immediately after; view already has cells loaded via load()
  if (activeView) activeView.exportAs(fmt);
}

async function deleteNotebook(id) {
  const n = find(id);
  if (!window.confirm('Delete "' + n.name + '"? Files are removed permanently.')) return;
  await api('/api/notebooks/' + id, 'DELETE');
  notebooks = notebooks.filter((x) => x.id !== id);
  if (activeId === id) {
    activeId = null;
    if (activeView) { activeView.destroy(); activeView = null; }
    history.pushState({}, '', '/');
    showEmpty();
  }
  render();
}

// ---- popstate ----
window.addEventListener('popstate', () => {
  const m = location.pathname.match(/^\/e\/([0-9a-f-]+)/);
  if (m && find(m[1])) {
    openNotebook(m[1], false);
  } else {
    activeId = null;
    if (activeView) { activeView.destroy(); activeView = null; }
    showEmpty();
    render();
  }
});

// ---- init ----
async function init() {
  initThemes();
  els.newBtn.onclick = () => newNotebook().catch((err) => alert('Launch failed: ' + err.message));
  els.search.oninput = (e) => { filter = e.target.value; render(); };
  els.logout.onclick = async () => {
    await api('/api/auth/logout', 'POST').catch(() => {});
    location.href = '/login';
  };
  try {
    els.email.textContent = (await api('/api/me')).email;
    notebooks = await api('/api/notebooks'); counter = notebooks.length;
    render();
    const m = location.pathname.match(/^\/e\/([0-9a-f-]+)/);
    if (m && find(m[1])) await openNotebook(m[1], false);
  } catch (e) {}
}
init();
