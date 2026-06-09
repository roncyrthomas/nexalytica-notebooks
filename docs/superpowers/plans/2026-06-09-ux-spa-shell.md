# UX Round 2 — SPA Shell, Theming, Export, Warm Kernels — Plan (4 of N)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Address 5 UX gaps: (1) loading feedback during cold start, (2) an always-present sidebar with instant notebook switching (SPA), (3) export (.ipynb/.py/.html), (4) warm kernels (reconnect via Jupyter sessions + cull idle kernels after 5 min) and a working theme selector, (5) friendly notebook names without changing the underlying id.

**Architecture:** Merge dashboard + editor into ONE theme-aware SPA shell reusing the existing `app.css`/`themes.css` chrome (sidebar grid, shimmer loader, context menu, 8 `data-nx` palettes). The `.main` pane hosts our notebook editor (re-styled to the semantic CSS vars). `shell.js` is the SPA controller (list/new/rename/delete/export/theme/logout/routing + loading overlay); `notebook.js` is a mountable/destroyable notebook **view**; `nbclient.js` gains Sessions + export helpers. Backend: containers cull idle kernels after 5 min; image gains nbconvert for HTML export.

**Tech Stack:** Vanilla JS (no build), FastAPI, Docker SDK.

**Depends on:** Plans 1–3 (runtime, broker API, Core UI).

---

## File Structure
- Modify: `broker/config.py` — `CULL_IDLE`, `CULL_INTERVAL` constants.
- Modify: `broker/docker_ops.py` — add kernel-cull flags to the container command.
- Modify: `broker/tests/test_docker_ops.py` — assert the cull flags.
- Modify: `Dockerfile` — ensure `nbconvert` installed (HTML export).
- Modify: `broker/static/nbclient.js` — add `Sessions` + `exportUrl` helpers.
- Rewrite: `broker/static/editor.css` — use the semantic theme vars (`--bg`, `--card`, …) instead of hardcoded `--nb-*`.
- Rewrite: `broker/static/index.html` — the SPA shell (sidebar + main with `#editor-root`, `#empty`, `#loading`).
- Create: `broker/static/notebook.js` — `NotebookView` (mount/destroy a single notebook into a container).
- Rewrite: `broker/static/app.js` → SPA controller (rename file stays `app.js`).
- Delete: `broker/static/editor.html` (merged into the shell).
- Modify: `broker/app.py` — `/e/{nid}` serves the shell (`index.html`), not `editor.html`.

---

## Task 1: Kernel cull config (backend)

**Files:** Modify `broker/config.py`, `broker/docker_ops.py`, `broker/tests/test_docker_ops.py`.

- [ ] **Step 1: Add constants to `broker/config.py`** (after `PIDS_LIMIT`)
```python
# kernel culling inside the container: free a kernel after 5 min idle so a
# closed/abandoned notebook stops consuming RAM, while reopening within the
# window reconnects to the still-live kernel (warm).
CULL_IDLE = int(os.environ.get("NEX_CULL_IDLE", "300"))      # seconds
CULL_INTERVAL = int(os.environ.get("NEX_CULL_INTERVAL", "60"))
```

- [ ] **Step 2: Failing test** — append to `broker/tests/test_docker_ops.py`
```python
def test_run_container_sets_kernel_cull():
    from unittest.mock import MagicMock
    client = MagicMock()
    ops = DockerOps(client=client)
    ops.run_container(user_id="u1", container_key="k", token="t",
                      volume="v", port=40000)
    cmd = " ".join(client.containers.run.call_args.kwargs["command"])
    assert f"cull_idle_timeout={config.CULL_IDLE}" in cmd
    assert "cull_connected=True" in cmd
```

- [ ] **Step 3: Run — expect FAIL.** `cd broker && python -m pytest tests/test_docker_ops.py -k cull -q`

- [ ] **Step 4: Edit `broker/docker_ops.py`** — add three flags to the `command` list in `run_container` (after `--ServerApp.allow_origin=*`):
```python
                f"--MappingKernelManager.cull_idle_timeout={config.CULL_IDLE}",
                f"--MappingKernelManager.cull_interval={config.CULL_INTERVAL}",
                "--MappingKernelManager.cull_connected=True",
```

- [ ] **Step 5: Run — expect PASS** and full suite green. `cd broker && python -m pytest -q`

- [ ] **Step 6: Commit** `feat(runtime): cull idle kernels after 5 min (warm reopen, then free)`

---

## Task 2: nbconvert in the image (HTML export)

**Files:** Modify `Dockerfile`.

- [ ] **Step 1: Edit the pip install line** in `Dockerfile` to include nbconvert:
```dockerfile
RUN pip install --no-cache-dir \
        "jupyterlab>=4.4,<4.5" "notebook>=7.4,<7.5" "jupyter-collaboration>=4,<5" \
        "nbconvert>=7" && \
    jupyter lab build 2>/dev/null || true && \
    fix-permissions "${CONDA_DIR}" && fix-permissions "/home/${NB_USER}"
```

- [ ] **Step 2: Commit** `chore(image): ensure nbconvert for HTML export`
(Note: requires rebuilding `nexalytica-notebook` to take effect.)

---

## Task 3: nbclient.js — Sessions + export helpers

**Files:** Modify `broker/static/nbclient.js`.

- [ ] **Step 1: Add a `Sessions` API and export URL helper** inside the IIFE, and include them in the exported `NB` object.
```javascript
  // Sessions bind a notebook path to a kernel. Reusing the session on reopen
  // reconnects to the SAME (warm) kernel instead of starting a cold one.
  const Sessions = {
    list: () => jfetch('/api/sessions'),
    create: (path) => jfetch('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({
        path, type: 'notebook', name: path,
        kernel: { name: 'python3' },
      }),
    }),
    // get-or-create the session for a notebook path; returns the session object
    ensure: async (path) => {
      const all = await Sessions.list();
      const existing = all.find((s) => s.path === path);
      return existing || Sessions.create(path);
    },
  };

  // nbconvert export endpoint (served by jupyter-server when nbconvert is
  // installed). format: 'html' | 'script'. Returns a same-origin URL the
  // browser can open/download; the broker injects the token server-side.
  function exportUrl(path, format) {
    return `${BASE}/nbconvert/${format}/${path}?download=true`;
  }

  global.NB = { Contents, Kernels, Sessions, KernelSession, exportUrl, uuid };
```
(Replace the existing `global.NB = {...}` line with the one above.)

- [ ] **Step 2: Syntax check.** `node --check broker/static/nbclient.js`
- [ ] **Step 3: Commit** `feat(ui): nbclient Sessions (warm reconnect) + export URLs`

---

## Task 4: editor.css — theme-aware (semantic vars)

**Files:** Rewrite `broker/static/editor.css`.

- [ ] **Step 1: Rewrite `broker/static/editor.css`** so all editor styles use the semantic
theme variables defined in `themes.css` (`--bg`, `--fg`, `--card`, `--primary`,
`--primary-fg`, `--border`, `--muted-fg`, `--radius`, `--font`) instead of hardcoded
`--nb-*`. Keep the same layout (app bar within the main pane, toolbar, cells, gutter,
textarea, outputs, hover actions). Concretely:
  - The editor lives inside `.main`; do NOT set `body` background here (the shell owns it).
  - Map: panel/app-bar bg → `var(--card)`; text → `var(--fg)`; borders → `var(--border)`;
    code/output bg → `color-mix(in oklch, var(--fg) 4%, var(--bg))`; primary button →
    `var(--primary)`/`var(--primary-fg)`; muted text → `var(--muted-fg)`; accent left-border
    on outputs → `var(--primary)`; error tint → `oklch(0.62 0.21 25)`.
  - Code font: keep a monospace stack; UI font inherits `var(--font)`.
  - Kernel dot states: idle → `var(--primary)`, busy → `oklch(0.75 0.15 85)`, dead →
    `oklch(0.62 0.21 25)`, starting/unknown → `var(--muted-fg)`.
Full file:
```css
/* Core editor — themed via the semantic vars in themes.css (data-nx). */
.nb-editor { display:flex; flex-direction:column; height:100%; min-height:0; }

.nb-appbar{display:flex;align-items:center;gap:12px;padding:10px 16px;
  background:var(--card);border-bottom:1px solid var(--border)}
.nb-title{font-weight:600;color:var(--fg)}
.nb-saved{font-size:12px;color:var(--muted-fg)}
.nb-spacer{flex:1}
.nb-kernel{display:flex;align-items:center;gap:8px;background:var(--bg);
  border:1px solid var(--border);border-radius:999px;padding:5px 12px;font-size:12.5px;color:var(--muted-fg)}
.k-dot{width:8px;height:8px;border-radius:50%;background:var(--muted-fg)}
.k-dot.idle{background:var(--primary)} .k-dot.busy{background:oklch(0.75 0.15 85)}
.k-dot.dead{background:oklch(0.62 0.21 25)}

.nb-toolbar{display:flex;align-items:center;gap:6px;padding:8px 16px;
  border-bottom:1px solid var(--border);background:var(--card)}
.nb-btn{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);
  background:var(--bg);color:var(--fg);padding:6px 12px;border-radius:8px;font:inherit;font-size:13px;cursor:pointer}
.nb-btn:hover{background:color-mix(in oklch,var(--fg) 7%,transparent)}
.nb-btn.primary{background:var(--primary);border-color:var(--primary);color:var(--primary-fg)}
.nb-sep{width:1px;height:20px;background:var(--border);margin:0 6px}

.nb-scroll{flex:1;overflow:auto;min-height:0}
.nb-cells{padding:20px 16px;max-width:1000px;margin:0 auto;display:flex;flex-direction:column;gap:12px}
.cell{position:relative;display:flex;gap:10px;border:1px solid transparent;border-radius:var(--radius);padding:6px}
.cell:hover{border-color:var(--border);background:color-mix(in oklch,var(--fg) 4%,transparent)}
.cell .gutter{width:54px;flex:0 0 54px;padding-top:10px;text-align:right;color:var(--muted-fg);
  font-family:ui-monospace,Consolas,monospace;font-size:12px;user-select:none}
.cell .main{flex:1;min-width:0}
.cell textarea{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);
  border-radius:8px;padding:10px 12px;font-family:ui-monospace,"Cascadia Code",Consolas,monospace;
  font-size:13px;line-height:1.5;resize:vertical;min-height:38px;outline:none}
.cell textarea:focus{border-color:color-mix(in oklch,var(--primary) 45%,var(--border))}
.cell .output{margin-top:8px;padding:9px 12px;background:color-mix(in oklch,var(--fg) 4%,var(--bg));
  border:1px solid var(--border);border-left:3px solid var(--primary);border-radius:8px;
  font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.5;white-space:pre-wrap;overflow:auto}
.cell .output.err{border-left-color:oklch(0.62 0.21 25);color:oklch(0.7 0.17 25)}
.cell .output img{max-width:100%;background:#fff;border-radius:4px}
.cell .md{padding:6px 4px;color:var(--fg);line-height:1.6}
.cell .actions{position:absolute;top:8px;right:10px;display:none;gap:4px;background:var(--card);
  border:1px solid var(--border);border-radius:8px;padding:3px}
.cell:hover .actions{display:flex}
.cell .actions button{width:26px;height:24px;display:grid;place-items:center;border:0;background:transparent;
  color:var(--muted-fg);border-radius:6px;cursor:pointer}
.cell .actions button:hover{background:color-mix(in oklch,var(--fg) 10%,transparent);color:var(--fg)}
```

- [ ] **Step 2: Commit** `feat(ui): editor styles use theme palette vars (8-palette parity)`

---

## Task 5: index.html — the SPA shell

**Files:** Rewrite `broker/static/index.html`; delete `broker/static/editor.html`.

- [ ] **Step 1: Rewrite `broker/static/index.html`** as the shell: the `.app` grid
(sidebar + main) reusing `app.css`, loading `themes.css`, `app.css`, `editor.css`, then
`nbclient.js`, `notebook.js`, `app.js`. The sidebar keeps: brand, New button, search,
notebook `#list`, and a footer with the theme `<select id="theme">`, account email + logout.
The `.main` contains `#editor-root` (where NotebookView mounts), an `#empty` placeholder,
and the `#loading` shimmer block (reuse the markup from the OLD index.html shimmer). Keep the
`#ctx-menu` with Open / Rename / Export / Delete items.
```html
<!DOCTYPE html>
<html lang="en" data-nx="default-dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Nexalytica Notebooks</title>
  <link rel="stylesheet" href="/static/themes.css" />
  <link rel="stylesheet" href="/static/app.css" />
  <link rel="stylesheet" href="/static/editor.css" />
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="side-head"><span class="brand-logo"></span><span class="brand-name">Nexalytica</span></div>
      <button class="new-btn" id="new-btn">&#43;&nbsp; New notebook</button>
      <div class="search"><input id="search" type="text" placeholder="Search notebooks&hellip;" autocomplete="off" /></div>
      <div class="section-label">Notebooks</div>
      <div class="list" id="list"></div>
      <div class="side-foot">
        <label for="theme">Theme</label>
        <select class="theme-select" id="theme"></select>
        <div class="acct"><span class="email" id="email">&hellip;</span><button class="logout" id="logout">Log out</button></div>
      </div>
    </aside>
    <main class="main">
      <div id="editor-root"></div>
      <div class="empty" id="empty">
        <div class="big">No notebook open</div>
        <div class="sub">Create or open a notebook from the sidebar to start an isolated session.</div>
      </div>
      <div class="loading" id="loading" hidden>
        <div class="sk">
          <div class="sk-bar w55"></div><div class="sk-bar w80"></div><div class="sk-bar w40"></div>
          <div class="sk-card"></div><div class="sk-bar w70"></div><div class="sk-bar w50"></div>
        </div>
        <div class="sk-note" id="loading-note">Starting your notebook&hellip;</div>
      </div>
    </main>
  </div>
  <div class="ctx-menu" id="ctx-menu" hidden>
    <button data-act="open">Open</button>
    <button data-act="rename">Rename</button>
    <button data-act="export-ipynb">Export .ipynb</button>
    <button data-act="export-py">Export .py</button>
    <button data-act="export-html">Export .html</button>
    <div class="sep"></div>
    <button data-act="delete" class="danger">Delete</button>
  </div>
  <script src="/static/nbclient.js"></script>
  <script src="/static/notebook.js"></script>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Delete the old editor page.** `git rm broker/static/editor.html`

- [ ] **Step 3: Add `#editor-root { position:absolute; inset:0; }` and `.empty/.loading` are
already absolute in app.css.** Append to `editor.css`:
```css
#editor-root{position:absolute;inset:0;display:none}
#editor-root.active{display:block}
```

- [ ] **Step 4: Commit** `feat(ui): unified SPA shell (sidebar + editor pane)`

---

## Task 6: notebook.js — mountable NotebookView

**Files:** Create `broker/static/notebook.js` by refactoring the current `editor.js` logic into
a constructor that mounts into a root element and can be destroyed on switch.

- [ ] **Step 1: Create `broker/static/notebook.js`.** Adapt ALL the logic from the current
`broker/static/editor.js` (read it) into:
```javascript
// notebook.js — a mountable view for ONE notebook. Reconnects to a warm kernel
// via Jupyter sessions; tears down its WS on destroy.
window.NotebookView = function (root, nid, hooks) {
  hooks = hooks || {};
  const path = `${nid}.ipynb`;
  let cells = [], kernelId = null, session = null, selectedCell = null, destroyed = false;
  const pending = {};
  // ... (esc, stripAnsi, mdToHtml, renderOutputs, makeCellEl, rerenderCell, renderAll,
  //      addCell, deleteCell, moveCell, runCell, runAll, save — same as editor.js,
  //      but: setKernel calls hooks.onKernel(state); the toolbar/cells are built into
  //      `root` rather than document-global ids.)

  // Kernel: reconnect to the notebook's existing session/kernel (warm) if any.
  async function ensureKernel() {
    if (session) return;
    hooks.onKernel && hooks.onKernel('starting');
    const s = await NB.Sessions.ensure(path);
    kernelId = s.kernel.id;
    session = NB.KernelSession(kernelId, { /* onStatus/onIO/onReply as in editor.js */ });
  }

  async function load() {
    const doc = await NB.Contents.get(path);
    hooks.onTitle && hooks.onTitle((doc.name || path).replace(/\.ipynb$/, ''));
    // map doc.content.cells -> cells; render into root; if a live kernel exists, set idle
  }

  function destroy() { destroyed = true; if (session) session.close(); root.innerHTML = ''; }

  load();
  return { destroy, save, getName: () => nid };
};
```
**Requirements (must match current editor.js behavior, plus):**
- Build the editor DOM **inside `root`** (an `.nb-editor` with `.nb-appbar` [title + saved +
  kernel pill], `.nb-toolbar` [Run, Run all, Interrupt, Restart, +Code, +Markdown, Save,
  Export▾], and `.nb-scroll > .nb-cells`). No global `document.getElementById` for editor
  controls — query within `root`.
- `hooks.onKernel(state)` updates the shell's kernel indicator; `hooks.onTitle(name)` updates
  the sidebar/active title.
- Kernel via `NB.Sessions.ensure(path)` (warm reconnect). On `destroy()`, close the WS but DO
  NOT delete the kernel (cull handles it) — so switching back within 5 min is warm.
- Export menu in the toolbar: `.ipynb` (download current serialized content as
  `<name>.ipynb`), `.py` (join code-cell sources, download `<name>.py`), `.html`
  (`window.open(NB.exportUrl(path,'html'))`). Use the friendly `name` for download filenames.
- Keep: run focused cell, Shift+Enter, restart flushes `pending`, output rendering for
  stream/error/execute_result/display_data, Ctrl/Cmd+S save.

- [ ] **Step 2: Syntax check.** `node --check broker/static/notebook.js`
- [ ] **Step 3: Commit** `feat(ui): NotebookView — mountable, warm-kernel notebook view`

---

## Task 7: app.js — SPA controller + loading + theme + rename + routing

**Files:** Rewrite `broker/static/app.js` (read the current one for the dashboard helpers to reuse).

- [ ] **Step 1: Rewrite `broker/static/app.js`** as the shell controller:
- Reuse the `THEMES` list + `applyTheme(id)` (sets `data-nx` on `<html>` + localStorage +
  the `<select>` value) from the ORIGINAL app.js (pre-Plan-3) — read it from git history
  (`git show 71934d3~1:broker/static/app.js`) or reconstruct the 8-entry list and handler.
  Populate `#theme` and wire `onchange` to `applyTheme`.
- `api(path, method, body)` helper (401 → /login) as today.
- Load `/api/me` (email) + `/api/notebooks` (list) → `render()` the sidebar list.
- **Routing:** read `location.pathname`; if `/e/<id>` and that id is in the list → open it.
  `openNotebook(id)` does `history.pushState({id}, '', '/e/'+id)`, shows the **loading
  overlay** (`#loading`, with note "Starting your notebook…"), tears down any current
  `NotebookView`, mounts a new `NotebookView('#editor-root', id, hooks)`, and on its first
  successful load hides the overlay + reveals `#editor-root.active`. `popstate` re-routes.
- **Loading feedback (#1):** show `#loading` immediately on open/create and hide only when the
  view reports loaded (hook) — so the cold-start wait is never silent. The kernel pill (in the
  view) shows "starting…" until connected.
- `newNotebook()` → POST, push to list, `openNotebook(newId)`.
- Sidebar item context menu (reuse `#ctx-menu`): Open, Rename (`prompt` → PATCH name, keep id,
  re-render + update title), Export .ipynb/.py/.html (delegate to the active view if open, else
  open the notebook then export), Delete (confirm → DELETE → drop from list; if active, clear
  the pane and route to `/`).
- Logout, search filter as today.

- [ ] **Step 2: Syntax check.** `node --check broker/static/app.js`
- [ ] **Step 3: Commit** `feat(ui): SPA controller — routing, loading overlay, theme, rename, export`

---

## Task 8: app.py — serve the shell for /e/<id>

**Files:** Modify `broker/app.py`.

- [ ] **Step 1: Change `editor_page`** so `/e/{nid}` returns the shell (`index.html`), not the
removed `editor.html`:
```python
@app.get("/e/{nid}")
def editor_page(request: Request, nid: str):
    if not _uid(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
```

- [ ] **Step 2: Import smoke + suite.** `cd broker && python -c "import app; print('ok')" && python -m pytest -q`
- [ ] **Step 3: Commit** `feat(ui): /e/<id> serves the SPA shell (deep-link safe)`

---

## Task 9 (Docker host): manual smoke
- [ ] Rebuild image (`docker build -t nexalytica-notebook .`), `python reset.py --yes`, `python run.py`.
- [ ] Verify: cold-start shows the shimmer + "Starting…"; sidebar persists; switch between two
  notebooks instantly; theme selector restyles everything (try a few palettes); rename keeps
  the URL/id; export .ipynb/.py/.html each download/open; run a cell, leave it <5 min, reopen →
  warm (same kernel, variables retained); wait >5 min → fresh kernel.

---

## Plan-vs-Spec Self-Review
- (1) loading → Task 7 overlay + Task 6 kernel "starting…". ✓
- (2) persistent sidebar + instant switch → Tasks 5–7 SPA. ✓
- (3) export → Task 3 helpers + Task 6 menu (.ipynb/.py client, .html via nbconvert + Task 2). ✓
- (4) warm kernel + cull + theme selector → Task 1 (cull) + Task 6 (sessions) + Task 7 (theme). ✓
- (5) friendly names → rename keeps id/path (already); Task 6/7 use `name` for title + export filenames. ✓
- Placeholder note: Task 6 shows the structure with `...` for logic that is a direct port of the
  current `editor.js` — the implementer MUST read `broker/static/editor.js` and carry every
  behavior over (it is not new logic, just relocated into the view + sessions + export).
```
