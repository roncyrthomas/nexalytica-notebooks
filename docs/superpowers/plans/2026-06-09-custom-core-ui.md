# Custom Core Notebook UI — Implementation Plan (Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A zero-build vanilla-JS "Core" notebook editor served from `broker/static/`, talking to the broker's `/api/nb/...` proxy (Plan 2). Code+markdown cells, run/run-all, add/delete/reorder, common outputs, save/load, kernel status + restart/interrupt. No JupyterLab, no terminal.

**Architecture:** `nbclient.js` (global `NB`) wraps the Jupyter REST contents/kernels API and the kernel WebSocket v5 message subset. `editor.js`/`editor.html`/`editor.css` render the notebook and drive `NB`. The dashboard (`app.js`/`index.html`) drops iframes and navigates to the editor page. `app.py` serves the editor page.

**Tech Stack:** Vanilla ES (no modules/build), Fetch + WebSocket, the broker `/api/nb` contract.

**Spec:** §6 of `docs/superpowers/specs/2026-06-08-per-user-container-platform-design.md` (UI revised to zero-build vanilla on 2026-06-09).

**Depends on:** Plan 2 (the `/api/nb` proxy + notebook CRUD).

**Testing note:** This is browser JS in a project with no JS test harness and no Docker on the dev box. Each task verifies by (a) a Node syntax check (`node --check file.js`) where possible, and (b) a documented manual smoke once running against a real container. An optional Playwright E2E is listed last and is expected to be run on a Docker-capable host.

---

## File Structure
- Create: `broker/static/nbclient.js` — Jupyter REST + kernel-WS client (global `NB`).
- Create: `broker/static/editor.html` — editor page shell.
- Create: `broker/static/editor.js` — notebook rendering + actions.
- Create: `broker/static/editor.css` — editor styles (rides on `themes.css`).
- Modify: `broker/static/app.js`, `broker/static/index.html` — dashboard: open → editor page (no iframes).
- Modify: `broker/app.py` — route `GET /e/{nid}` → `editor.html`.

---

## Task 1: nbclient.js — REST + kernel-WS client

**Files:** Create `broker/static/nbclient.js`.

- [ ] **Step 1: Create `broker/static/nbclient.js`**

```javascript
// nbclient.js — minimal Jupyter client over the broker's /api/nb proxy.
// Exposes a global `NB` with Contents, Kernels, and a KernelSession (WS v5 subset).
// The broker injects the Jupyter token server-side; this code never sees it.
(function (global) {
  const BASE = '/api/nb';

  async function jfetch(path, opts) {
    opts = opts || {};
    const res = await fetch(BASE + path, {
      method: opts.method || 'GET',
      headers: Object.assign(
        opts.body ? { 'Content-Type': 'application/json' } : {},
        opts.headers || {}),
      body: opts.body || undefined,
    });
    if (res.status === 401) { location.href = '/login'; throw new Error('unauthorized'); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).message || detail; } catch (e) {}
      throw new Error(`${res.status} ${detail}`);
    }
    return res.status === 204 ? null : res.json();
  }

  const Contents = {
    // path is relative to the container work root, e.g. "<id>.ipynb"
    get: (path) => jfetch(`/api/contents/${path}?content=1&type=notebook`),
    save: (path, content) => jfetch(`/api/contents/${path}`, {
      method: 'PUT',
      body: JSON.stringify({ type: 'notebook', format: 'json', content }),
    }),
  };

  const Kernels = {
    start: () => jfetch('/api/kernels', {
      method: 'POST', body: JSON.stringify({ name: 'python3' }),
    }),
    interrupt: (id) => jfetch(`/api/kernels/${id}/interrupt`, { method: 'POST' }),
    restart: (id) => jfetch(`/api/kernels/${id}/restart`, { method: 'POST' }),
  };

  function uuid() {
    return (crypto.randomUUID && crypto.randomUUID()) ||
      'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
      });
  }

  // A live kernel connection. Callbacks:
  //   onIO(msgType, content, parentMsgId)  — iopub messages
  //   onStatus(state)                      — 'busy' | 'idle' | 'starting' | 'dead'
  //   onReply(parentMsgId, content)        — shell execute_reply
  function KernelSession(kernelId, cbs) {
    const sessionId = uuid();
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${scheme}://${location.host}${BASE}/api/kernels/${kernelId}/channels?session_id=${sessionId}`;
    let ws = null, open = false;

    function connect() {
      ws = new WebSocket(url);
      ws.onopen = () => { open = true; cbs.onStatus && cbs.onStatus('idle'); };
      ws.onclose = () => { open = false; cbs.onStatus && cbs.onStatus('dead'); };
      ws.onerror = () => { cbs.onStatus && cbs.onStatus('dead'); };
      ws.onmessage = (ev) => {
        let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
        const parentId = (m.parent_header && m.parent_header.msg_id) || null;
        if (m.channel === 'iopub') {
          if (m.header.msg_type === 'status') {
            cbs.onStatus && cbs.onStatus(m.content.execution_state);
          }
          cbs.onIO && cbs.onIO(m.header.msg_type, m.content, parentId);
        } else if (m.channel === 'shell') {
          if (m.header.msg_type === 'execute_reply') {
            cbs.onReply && cbs.onReply(parentId, m.content);
          }
        }
      };
    }
    connect();

    function execute(code) {
      const msgId = uuid();
      const msg = {
        header: {
          msg_id: msgId, session: sessionId, username: 'user',
          msg_type: 'execute_request', version: '5.3',
          date: new Date().toISOString(),
        },
        parent_header: {}, metadata: {},
        content: {
          code, silent: false, store_history: true,
          user_expressions: {}, allow_stdin: false, stop_on_error: true,
        },
        channel: 'shell', buffers: [],
      };
      if (!open) { throw new Error('kernel not connected'); }
      ws.send(JSON.stringify(msg));
      return msgId;
    }

    function close() { try { ws && ws.close(); } catch (e) {} }

    return { execute, close };
  }

  global.NB = { Contents, Kernels, KernelSession, uuid };
})(window);
```

- [ ] **Step 2: Syntax check**

Run: `node --check broker/static/nbclient.js`
Expected: no output (exit 0). If `node` is unavailable, open in browser devtools later; report that node was unavailable.

- [ ] **Step 3: Commit**

```bash
git add broker/static/nbclient.js
git commit -m "feat(ui): Jupyter REST + kernel-WS client (vanilla, zero-build)"
```

---

## Task 2: editor.html + editor.css

**Files:** Create `broker/static/editor.html`, `broker/static/editor.css`.

- [ ] **Step 1: Create `broker/static/editor.html`**

```html
<!DOCTYPE html>
<html lang="en" data-nx="default-dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Notebook</title>
  <link rel="stylesheet" href="/static/themes.css" />
  <link rel="stylesheet" href="/static/editor.css" />
</head>
<body>
  <header class="nb-appbar">
    <a class="nb-back" href="/" title="Back to notebooks">&#8592;</a>
    <span class="nb-name" id="nb-name">Notebook</span>
    <span class="nb-saved" id="nb-saved"></span>
    <div class="nb-spacer"></div>
    <span class="nb-kernel" id="nb-kernel"><span class="k-dot" id="k-dot"></span><span id="k-text">starting&hellip;</span></span>
  </header>

  <div class="nb-toolbar">
    <button class="nb-btn primary" id="t-run">&#9654; Run</button>
    <button class="nb-btn" id="t-runall">&#9197; Run all</button>
    <span class="nb-sep"></span>
    <button class="nb-btn" id="t-interrupt">&#9632; Interrupt</button>
    <button class="nb-btn" id="t-restart">&#8635; Restart</button>
    <span class="nb-sep"></span>
    <button class="nb-btn" id="t-addcode">&#43; Code</button>
    <button class="nb-btn" id="t-addmd">&#43; Markdown</button>
    <div class="nb-spacer"></div>
    <button class="nb-btn" id="t-save">Save</button>
  </div>

  <main class="nb-cells" id="cells"></main>

  <script src="/static/nbclient.js"></script>
  <script src="/static/editor.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `broker/static/editor.css`**

```css
:root{
  --nb-bg:#0f1117; --nb-panel:#161922; --nb-panel2:#1b1f2a; --nb-border:#262b38;
  --nb-text:#e6e9f0; --nb-muted:#8b93a7; --nb-accent:#6c7bff; --nb-accent2:#36c5a8;
  --nb-in:#11141d; --nb-code:#0c0e14; --nb-red:#f85149; --nb-green:#3fb950;
  --nb-mono:ui-monospace,"Cascadia Code","Fira Code",Consolas,monospace;
  --nb-sans:"Inter",-apple-system,"Segoe UI",Roboto,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--nb-bg);color:var(--nb-text);font-family:var(--nb-sans)}
.nb-appbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;
  padding:10px 16px;background:rgba(15,17,23,.9);border-bottom:1px solid var(--nb-border)}
.nb-back{color:var(--nb-muted);text-decoration:none;font-size:18px}
.nb-back:hover{color:var(--nb-text)}
.nb-name{font-weight:600}
.nb-saved{font-size:12px;color:var(--nb-muted)}
.nb-spacer{flex:1}
.nb-kernel{display:flex;align-items:center;gap:8px;background:var(--nb-panel2);
  border:1px solid var(--nb-border);border-radius:999px;padding:5px 12px;font-size:12.5px;color:var(--nb-muted)}
.k-dot{width:8px;height:8px;border-radius:50%;background:var(--nb-muted)}
.k-dot.idle{background:var(--nb-green);box-shadow:0 0 8px var(--nb-green)}
.k-dot.busy{background:#d29922;box-shadow:0 0 8px #d29922}
.k-dot.dead{background:var(--nb-red)}
.nb-toolbar{display:flex;align-items:center;gap:6px;padding:8px 16px;
  border-bottom:1px solid var(--nb-border);background:var(--nb-panel)}
.nb-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--nb-border);
  background:var(--nb-panel2);color:var(--nb-text);padding:6px 12px;border-radius:8px;
  font-size:13px;cursor:pointer}
.nb-btn:hover{background:#222838}
.nb-btn.primary{background:var(--nb-accent);border-color:var(--nb-accent);color:#fff}
.nb-sep{width:1px;height:20px;background:var(--nb-border);margin:0 6px}
.nb-cells{padding:20px 16px;max-width:1000px;margin:0 auto;display:flex;flex-direction:column;gap:12px}
.cell{position:relative;display:flex;gap:10px;border:1px solid transparent;border-radius:10px;padding:4px}
.cell:hover{border-color:var(--nb-border);background:#12151d}
.cell .gutter{width:54px;flex:0 0 54px;padding-top:10px;text-align:right;color:var(--nb-muted);
  font-family:var(--nb-mono);font-size:12px;user-select:none}
.cell .main{flex:1;min-width:0}
.cell textarea{width:100%;background:var(--nb-in);color:var(--nb-text);border:1px solid var(--nb-border);
  border-radius:8px;padding:10px 12px;font-family:var(--nb-mono);font-size:13px;line-height:1.5;
  resize:vertical;min-height:38px;outline:none}
.cell textarea:focus{border-color:var(--nb-accent)}
.cell .output{margin-top:8px;padding:9px 12px;background:var(--nb-code);border:1px solid var(--nb-border);
  border-left:3px solid var(--nb-accent2);border-radius:8px;font-family:var(--nb-mono);font-size:12.5px;
  line-height:1.5;white-space:pre-wrap;overflow:auto}
.cell .output.err{border-left-color:var(--nb-red);color:#ffb4ad}
.cell .output img{max-width:100%;background:#fff;border-radius:4px}
.cell .md{padding:6px 4px;color:#c8cfdd;line-height:1.6}
.cell .md h1,.cell .md h2,.cell .md h3{color:var(--nb-text)}
.cell .actions{position:absolute;top:8px;right:10px;display:none;gap:4px;
  background:var(--nb-panel2);border:1px solid var(--nb-border);border-radius:8px;padding:3px}
.cell:hover .actions{display:flex}
.cell .actions button{width:26px;height:24px;display:grid;place-items:center;border:0;background:transparent;
  color:var(--nb-muted);border-radius:6px;cursor:pointer}
.cell .actions button:hover{background:#2a3145;color:var(--nb-text)}
```

- [ ] **Step 2b: Commit**

```bash
git add broker/static/editor.html broker/static/editor.css
git commit -m "feat(ui): Core notebook editor page shell + styles"
```

---

## Task 3: editor.js — render, execute, save

**Files:** Create `broker/static/editor.js`.

- [ ] **Step 1: Create `broker/static/editor.js`**

```javascript
// editor.js — Core notebook editor. Loads a notebook by id (from the URL),
// renders cells, runs them over a kernel WS, renders outputs, and saves.
(function () {
  const nid = location.pathname.split('/').pop().replace(/\.ipynb$/, '');
  const path = `${nid}.ipynb`;

  const els = {
    cells: document.getElementById('cells'),
    name: document.getElementById('nb-name'),
    saved: document.getElementById('nb-saved'),
    kDot: document.getElementById('k-dot'),
    kText: document.getElementById('k-text'),
  };

  let cells = [];          // {id, type:'code'|'markdown', source, outputs:[], count:null, el, rendered}
  let kernelId = null, session = null;
  const pending = {};      // execute msg_id -> cell.id

  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*m/g, '');

  function setKernel(state) {
    els.kDot.className = 'k-dot ' + (state === 'idle' || state === 'busy' || state === 'dead' ? state : '');
    els.kText.textContent = state === 'starting' ? 'starting…' : `Python 3 · ${state}`;
  }

  // ---- minimal markdown (headings, bold, inline code) ----
  function mdToHtml(src) {
    return esc(src)
      .replace(/^### (.*)$/gm, '<h3>$1</h3>')
      .replace(/^## (.*)$/gm, '<h2>$1</h2>')
      .replace(/^# (.*)$/gm, '<h1>$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
  }

  // ---- output rendering ----
  function renderOutputs(cell) {
    const host = cell.el.querySelector('.outputs');
    host.innerHTML = '';
    for (const o of cell.outputs) {
      const div = document.createElement('div');
      div.className = 'output';
      if (o.output_type === 'stream') {
        if (o.name === 'stderr') div.classList.add('err');
        div.textContent = o.text;
      } else if (o.output_type === 'error') {
        div.classList.add('err');
        div.textContent = stripAnsi((o.traceback || []).join('\n')) ||
          `${o.ename}: ${o.evalue}`;
      } else { // execute_result | display_data
        const d = o.data || {};
        if (d['image/png']) {
          const img = document.createElement('img');
          img.src = 'data:image/png;base64,' + d['image/png'];
          div.appendChild(img);
        } else if (d['text/html']) {
          div.innerHTML = d['text/html'];           // trusted: user's own kernel output
        } else if (d['text/plain']) {
          div.textContent = d['text/plain'];
        } else { div.textContent = '[unsupported output]'; }
      }
      host.appendChild(div);
    }
  }

  // ---- cell DOM ----
  function makeCellEl(cell) {
    const el = document.createElement('div');
    el.className = 'cell';
    el.innerHTML =
      `<div class="actions">
         <button data-act="run" title="Run">&#9654;</button>
         <button data-act="up" title="Up">&#8593;</button>
         <button data-act="down" title="Down">&#8595;</button>
         <button data-act="del" title="Delete">&#128465;</button>
       </div>
       <div class="gutter"><span class="cnt"></span></div>
       <div class="main"></div>`;
    const main = el.querySelector('.main');
    if (cell.type === 'markdown' && cell.rendered) {
      const md = document.createElement('div');
      md.className = 'md'; md.innerHTML = mdToHtml(cell.source);
      md.ondblclick = () => { cell.rendered = false; rerenderCell(cell); };
      main.appendChild(md);
    } else {
      const ta = document.createElement('textarea');
      ta.value = cell.source; ta.rows = Math.max(1, cell.source.split('\n').length);
      ta.oninput = () => { cell.source = ta.value; ta.rows = Math.max(1, ta.value.split('\n').length); };
      ta.onkeydown = (e) => {
        if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); runCell(cell); }
      };
      main.appendChild(ta);
    }
    const outs = document.createElement('div'); outs.className = 'outputs'; main.appendChild(outs);
    el.querySelector('.actions').onclick = (e) => {
      const act = e.target.getAttribute('data-act'); if (!act) return;
      if (act === 'run') runCell(cell);
      else if (act === 'del') deleteCell(cell);
      else if (act === 'up') moveCell(cell, -1);
      else if (act === 'down') moveCell(cell, 1);
    };
    cell.el = el;
    el.querySelector('.cnt').textContent = cell.count != null ? `[${cell.count}]` : (cell.type === 'code' ? '[ ]' : '');
    return el;
  }

  function rerenderCell(cell) {
    const fresh = makeCellEl(cell);
    cell.el.replaceWith(fresh);
    renderOutputs(cell);
  }

  function renderAll() {
    els.cells.innerHTML = '';
    for (const c of cells) { els.cells.appendChild(makeCellEl(c)); renderOutputs(c); }
  }

  // ---- actions ----
  function addCell(type, after) {
    const cell = { id: NB.uuid(), type, source: '', outputs: [], count: null, rendered: false };
    const idx = after ? cells.indexOf(after) + 1 : cells.length;
    cells.splice(idx, 0, cell); renderAll();
  }
  function deleteCell(cell) { cells = cells.filter((c) => c !== cell); renderAll(); }
  function moveCell(cell, dir) {
    const i = cells.indexOf(cell), j = i + dir;
    if (j < 0 || j >= cells.length) return;
    cells.splice(i, 1); cells.splice(j, 0, cell); renderAll();
  }

  async function ensureKernel() {
    if (session) return;
    setKernel('starting');
    const k = await NB.Kernels.start();
    kernelId = k.id;
    session = NB.KernelSession(kernelId, {
      onStatus: setKernel,
      onIO: (type, content, parentId) => {
        const cid = pending[parentId]; if (!cid) return;
        const cell = cells.find((c) => c.id === cid); if (!cell) return;
        if (type === 'execute_input') { cell.count = content.execution_count; cell.el.querySelector('.cnt').textContent = `[${cell.count}]`; }
        else if (type === 'stream') { cell.outputs.push({ output_type: 'stream', name: content.name, text: content.text }); renderOutputs(cell); }
        else if (type === 'execute_result' || type === 'display_data') { cell.outputs.push({ output_type: type, data: content.data }); renderOutputs(cell); }
        else if (type === 'error') { cell.outputs.push({ output_type: 'error', ename: content.ename, evalue: content.evalue, traceback: content.traceback }); renderOutputs(cell); }
      },
      onReply: (parentId) => { delete pending[parentId]; },
    });
  }

  async function runCell(cell) {
    if (cell.type === 'markdown') { cell.rendered = true; rerenderCell(cell); return; }
    await ensureKernel();
    cell.outputs = []; renderOutputs(cell);
    const msgId = session.execute(cell.source);
    pending[msgId] = cell.id;
  }
  async function runAll() { for (const c of cells) { if (c.type === 'code') await runCell(c); } }

  async function save() {
    const content = {
      nbformat: 4, nbformat_minor: 5,
      metadata: { kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' }, language_info: { name: 'python' } },
      cells: cells.map((c) => ({
        cell_type: c.type, metadata: {},
        source: c.source.split(/(?<=\n)/),
        ...(c.type === 'code' ? { outputs: [], execution_count: c.count } : {}),
      })),
    };
    await NB.Contents.save(path, content);
    els.saved.textContent = 'saved';
    setTimeout(() => { els.saved.textContent = ''; }, 1500);
  }

  // ---- toolbar ----
  document.getElementById('t-run').onclick = () => { const c = cells[0]; if (c) runCell(c); };
  document.getElementById('t-runall').onclick = runAll;
  document.getElementById('t-interrupt').onclick = () => kernelId && NB.Kernels.interrupt(kernelId);
  document.getElementById('t-restart').onclick = async () => {
    if (kernelId) { await NB.Kernels.restart(kernelId); for (const c of cells) { c.count = null; c.outputs = []; } renderAll(); }
  };
  document.getElementById('t-addcode').onclick = () => addCell('code');
  document.getElementById('t-addmd').onclick = () => addCell('markdown');
  document.getElementById('t-save').onclick = () => save().catch((e) => alert('Save failed: ' + e.message));
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save().catch(() => {}); }
  });

  // ---- load ----
  async function load() {
    try {
      const doc = await NB.Contents.get(path);
      els.name.textContent = (doc.name || path).replace(/\.ipynb$/, '');
      const nb = doc.content || { cells: [] };
      cells = (nb.cells || []).map((c) => ({
        id: NB.uuid(),
        type: c.cell_type === 'markdown' ? 'markdown' : 'code',
        source: Array.isArray(c.source) ? c.source.join('') : (c.source || ''),
        outputs: [], count: c.execution_count != null ? c.execution_count : null,
        rendered: c.cell_type === 'markdown',
      }));
      if (cells.length === 0) addCell('code'); else renderAll();
    } catch (e) {
      els.cells.innerHTML = `<div class="output err">Failed to load notebook: ${esc(e.message)}</div>`;
    }
  }
  load();
})();
```

- [ ] **Step 2: Syntax check**

Run: `node --check broker/static/editor.js`
Expected: exit 0 (the lookbehind `(?<=\n)` requires Node 9+; if node is unavailable, report it).

- [ ] **Step 3: Commit**

```bash
git add broker/static/editor.js
git commit -m "feat(ui): Core editor — render, execute over kernel WS, save"
```

---

## Task 4: app.py — serve the editor page

**Files:** Modify `broker/app.py`.

- [ ] **Step 1: Add the editor route** (near the other page routes)

```python
@app.get("/e/{nid}")
def editor_page(request: Request, nid: str):
    if not _uid(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "editor.html"))
```

- [ ] **Step 2: Import smoke**

Run: `cd broker && python -c "import app; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add broker/app.py
git commit -m "feat(ui): serve the Core editor page at /e/<id>"
```

---

## Task 5: Dashboard — open into the editor (drop iframes)

**Files:** Modify `broker/static/app.js`, `broker/static/index.html`.

- [ ] **Step 1: Simplify `broker/static/index.html`** — remove the `frames`/`loading`/`empty`
iframe workspace from `<main>`, leaving the sidebar list. Replace the `<main class="main">…</main>`
block with:
```html
    <main class="main">
      <div class="dash-head"><h1>Your notebooks</h1></div>
      <div class="empty" id="empty">
        <div class="big">Select or create a notebook</div>
        <div class="sub">Open a notebook from the sidebar to start an isolated session.</div>
      </div>
    </main>
```

- [ ] **Step 2: Replace `broker/static/app.js`** with a dashboard-only version (no iframes,
no theme-to-frame, no open/close container calls — opening navigates to the editor page):

```javascript
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
```

- [ ] **Step 2b: Remove the now-unused theme `<select>` handler dependency** — the new `app.js`
no longer references `#theme`. Leaving the element in `index.html` is harmless; optionally
remove the `<select id="theme">` and its `<label>` from the sidebar footer to avoid a dead control.

- [ ] **Step 3: Syntax check both**

Run: `node --check broker/static/app.js`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add broker/static/app.js broker/static/index.html
git commit -m "feat(ui): dashboard opens notebooks in the Core editor (no iframes)"
```

---

## Task 6 (optional, Docker host): End-to-end smoke + Playwright

Run this on a machine with Docker + the `nexalytica-notebook` image.

- [ ] **Step 1: Reset + start broker**

```bash
cd broker && python reset.py --yes && python run.py
```

- [ ] **Step 2: Manual smoke** — register, create a notebook, type `print(2+2)`, Shift+Enter,
confirm `4` renders; run `import pandas as pd; pd.DataFrame({'a':[1,2]})` and confirm an HTML
table; run a cell that raises and confirm a red traceback; Save; reload `/e/<id>` and confirm
source persists; Restart kernel and confirm counts clear.

- [ ] **Step 3 (optional): Playwright E2E** at `broker/tests/e2e/notebook.spec.ts` covering the
create → run → output → save → reload flow. (Defer if Playwright is not set up.)

- [ ] **Step 4: Document results** in the PR description (what passed; environment).

---

## Plan-vs-Spec Self-Review
- §6.2 components → editor.js (cells, outputs, kernel status, toolbar). ✓
- §6.3 data flow (load contents → execute over WS → save nbformat) → Task 1 + Task 3. ✓
- §6.4 output rendering (text/html/png/error) → `renderOutputs`. ✓
- §6.5 error handling (kernel dead/restart, load failure, WS) → `setKernel('dead')`, load catch. ✓
- No terminal, no Lab. ✓
- Placeholder scan: none — full code provided for every JS/HTML/CSS file.
- Known Core limitations (by design, deferred): no autocomplete, no file sidebar, no tabs,
  no ipywidgets; markdown is minimal; code editor is a textarea (CodeMirror is a later upgrade).
```
