// notebook.js — a mountable view for ONE notebook. Reconnects to a warm kernel
// via Jupyter sessions; tears down its WS on destroy.
window.NotebookView = function (root, nid, hooks) {
  hooks = hooks || {};
  const path = nid + '.ipynb';
  let cells = [], kernelId = null, session = null, selectedCell = null, destroyed = false;
  const pending = {};   // execute msg_id -> cell.id
  let notebookName = nid;

  // ---- DOM refs (all scoped to root) ----
  let elCells, elName, elSaved, elKDot, elKText;

  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*m/g, '');

  function setKernel(state) {
    if (destroyed) return;
    elKDot.className = 'k-dot ' + (state === 'idle' || state === 'busy' || state === 'dead' ? state : '');
    elKText.textContent = state === 'starting' ? 'starting…' : 'Python 3 · ' + state;
    hooks.onKernel && hooks.onKernel(state);
  }

  function setSaved(msg) {
    if (destroyed) return;
    elSaved.textContent = msg;
  }

  // ---- minimal markdown ----
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
        div.textContent = stripAnsi((o.traceback || []).join('\n')) || (o.ename + ': ' + o.evalue);
      } else {
        const d = o.data || {};
        if (d['image/png']) {
          const img = document.createElement('img');
          img.src = 'data:image/png;base64,' + d['image/png'];
          div.appendChild(img);
        } else if (d['text/html']) {
          div.innerHTML = d['text/html'];
        } else if (d['text/plain']) {
          div.textContent = d['text/plain'];
        } else {
          div.textContent = '[unsupported output]';
        }
      }
      host.appendChild(div);
    }
  }

  // ---- cell DOM ----
  function makeCellEl(cell) {
    const el = document.createElement('div');
    el.className = 'cell';
    el.innerHTML =
      '<div class="actions">' +
        '<button data-act="run" title="Run">&#9654;</button>' +
        '<button data-act="up" title="Up">&#8593;</button>' +
        '<button data-act="down" title="Down">&#8595;</button>' +
        '<button data-act="del" title="Delete">&#128465;</button>' +
      '</div>' +
      '<div class="gutter"><span class="cnt"></span></div>' +
      '<div class="main"></div>';
    const main = el.querySelector('.main');
    if (cell.type === 'markdown' && cell.rendered) {
      const md = document.createElement('div');
      md.className = 'md';
      md.innerHTML = mdToHtml(cell.source);
      md.ondblclick = function () { cell.rendered = false; rerenderCell(cell); };
      main.appendChild(md);
    } else {
      const ta = document.createElement('textarea');
      ta.value = cell.source;
      ta.rows = Math.max(1, cell.source.split('\n').length);
      ta.onfocus = function () { selectedCell = cell; };
      ta.oninput = function () {
        cell.source = ta.value;
        ta.rows = Math.max(1, ta.value.split('\n').length);
      };
      ta.onkeydown = function (e) {
        if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); runCell(cell); }
      };
      main.appendChild(ta);
    }
    const outs = document.createElement('div');
    outs.className = 'outputs';
    main.appendChild(outs);
    el.querySelector('.actions').onclick = function (e) {
      const act = e.target.getAttribute('data-act');
      if (!act) return;
      if (act === 'run') runCell(cell);
      else if (act === 'del') deleteCell(cell);
      else if (act === 'up') moveCell(cell, -1);
      else if (act === 'down') moveCell(cell, 1);
    };
    cell.el = el;
    el.querySelector('.cnt').textContent = cell.count != null ? '[' + cell.count + ']' : (cell.type === 'code' ? '[ ]' : '');
    return el;
  }

  function rerenderCell(cell) {
    const fresh = makeCellEl(cell);
    cell.el.replaceWith(fresh);
    renderOutputs(cell);
  }

  function renderAll() {
    elCells.innerHTML = '';
    for (const c of cells) { elCells.appendChild(makeCellEl(c)); renderOutputs(c); }
  }

  // ---- actions ----
  function addCell(type, after) {
    const cell = { id: NB.uuid(), type: type, source: '', outputs: [], count: null, rendered: false };
    const idx = after ? cells.indexOf(after) + 1 : cells.length;
    cells.splice(idx, 0, cell);
    renderAll();
  }
  function deleteCell(cell) { cells = cells.filter(function (c) { return c !== cell; }); renderAll(); }
  function moveCell(cell, dir) {
    const i = cells.indexOf(cell), j = i + dir;
    if (j < 0 || j >= cells.length) return;
    cells.splice(i, 1); cells.splice(j, 0, cell); renderAll();
  }

  async function ensureKernel() {
    if (session) return;
    setKernel('starting');
    const s = await NB.Sessions.ensure(path);
    kernelId = s.kernel.id;
    session = NB.KernelSession(kernelId, {
      onStatus: setKernel,
      onIO: function (type, content, parentId) {
        const cid = pending[parentId]; if (!cid) return;
        const cell = cells.find(function (c) { return c.id === cid; }); if (!cell) return;
        if (type === 'execute_input') {
          cell.count = content.execution_count;
          cell.el.querySelector('.cnt').textContent = '[' + cell.count + ']';
        } else if (type === 'stream') {
          cell.outputs.push({ output_type: 'stream', name: content.name, text: content.text });
          renderOutputs(cell);
        } else if (type === 'execute_result' || type === 'display_data') {
          cell.outputs.push({ output_type: type, data: content.data });
          renderOutputs(cell);
        } else if (type === 'error') {
          cell.outputs.push({ output_type: 'error', ename: content.ename, evalue: content.evalue, traceback: content.traceback });
          renderOutputs(cell);
        }
      },
      onReply: function (parentId) { delete pending[parentId]; },
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
      cells: cells.map(function (c) {
        return Object.assign(
          { cell_type: c.type, metadata: {}, source: c.source.split(/(?<=\n)/) },
          c.type === 'code' ? { outputs: [], execution_count: c.count } : {}
        );
      }),
    };
    await NB.Contents.save(path, content);
    setSaved('saved');
    setTimeout(function () { setSaved(''); }, 1500);
  }

  // ---- export ----
  function exportAs(fmt) {
    const name = notebookName || nid;
    if (fmt === 'ipynb') {
      const content = {
        nbformat: 4, nbformat_minor: 5,
        metadata: { kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' }, language_info: { name: 'python' } },
        cells: cells.map(function (c) {
          return Object.assign(
            { cell_type: c.type, metadata: {}, source: c.source.split(/(?<=\n)/) },
            c.type === 'code' ? { outputs: [], execution_count: c.count } : {}
          );
        }),
      };
      const blob = new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name + '.ipynb';
      a.click();
      URL.revokeObjectURL(a.href);
    } else if (fmt === 'py') {
      const src = cells
        .filter(function (c) { return c.type === 'code'; })
        .map(function (c) { return c.source; })
        .join('\n\n');
      const blob = new Blob([src], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = name + '.py';
      a.click();
      URL.revokeObjectURL(a.href);
    } else if (fmt === 'html') {
      window.open(NB.exportUrl(path, 'html'), '_blank');
    }
  }

  // ---- build DOM inside root ----
  function buildDOM() {
    root.innerHTML = '';
    root.className = 'nb-editor';

    // appbar
    const appbar = document.createElement('div');
    appbar.className = 'nb-appbar';
    appbar.innerHTML =
      '<span class="nb-title" id="nb-name-' + nid + '"></span>' +
      '<span class="nb-saved" id="nb-saved-' + nid + '"></span>' +
      '<span class="nb-spacer"></span>' +
      '<div class="nb-kernel">' +
        '<span class="k-dot" id="k-dot-' + nid + '"></span>' +
        '<span id="k-text-' + nid + '">not connected</span>' +
      '</div>';
    root.appendChild(appbar);

    elName  = appbar.querySelector('#nb-name-'  + nid);
    elSaved = appbar.querySelector('#nb-saved-' + nid);
    elKDot  = appbar.querySelector('#k-dot-'    + nid);
    elKText = appbar.querySelector('#k-text-'   + nid);

    // toolbar
    const toolbar = document.createElement('div');
    toolbar.className = 'nb-toolbar';

    function mkBtn(id, label, primary) {
      const b = document.createElement('button');
      b.className = 'nb-btn' + (primary ? ' primary' : '');
      b.id = id; b.innerHTML = label;
      toolbar.appendChild(b);
      return b;
    }
    function mkSep() {
      const s = document.createElement('span'); s.className = 'nb-sep'; toolbar.appendChild(s);
    }

    const btnRun       = mkBtn('t-run-'       + nid, '&#9654; Run');
    const btnRunAll    = mkBtn('t-runall-'     + nid, 'Run all');
    const btnInterrupt = mkBtn('t-interrupt-'  + nid, 'Interrupt');
    const btnRestart   = mkBtn('t-restart-'    + nid, 'Restart');
    mkSep();
    const btnAddCode   = mkBtn('t-addcode-'    + nid, '+ Code');
    const btnAddMd     = mkBtn('t-addmd-'      + nid, '+ Markdown');
    mkSep();
    const btnSave      = mkBtn('t-save-'       + nid, 'Save', true);

    // Export dropdown
    const exportWrap = document.createElement('div');
    exportWrap.style.cssText = 'position:relative;display:inline-flex';
    const btnExport = document.createElement('button');
    btnExport.className = 'nb-btn';
    btnExport.innerHTML = 'Export &#9660;';
    const exportMenu = document.createElement('div');
    exportMenu.style.cssText = 'display:none;position:absolute;top:100%;right:0;background:var(--card);border:1px solid var(--border);border-radius:8px;z-index:100;min-width:140px;padding:4px 0';
    function mkExportItem(fmt, label) {
      const b = document.createElement('button');
      b.style.cssText = 'display:block;width:100%;text-align:left;padding:8px 14px;border:0;background:transparent;color:var(--fg);font:inherit;font-size:13px;cursor:pointer';
      b.textContent = label;
      b.onmouseenter = function () { b.style.background = 'color-mix(in oklch,var(--fg) 8%,transparent)'; };
      b.onmouseleave = function () { b.style.background = 'transparent'; };
      b.onclick = function () { exportMenu.style.display = 'none'; exportAs(fmt); };
      exportMenu.appendChild(b);
    }
    mkExportItem('ipynb', 'Download .ipynb');
    mkExportItem('py',    'Download .py');
    mkExportItem('html',  'Open as .html');
    exportWrap.appendChild(btnExport);
    exportWrap.appendChild(exportMenu);
    toolbar.appendChild(exportWrap);

    btnExport.onclick = function (e) {
      e.stopPropagation();
      exportMenu.style.display = exportMenu.style.display === 'none' ? 'block' : 'none';
    };
    document.addEventListener('click', function () { exportMenu.style.display = 'none'; });

    root.appendChild(toolbar);

    // scroll + cells
    const scroll = document.createElement('div');
    scroll.className = 'nb-scroll';
    elCells = document.createElement('div');
    elCells.className = 'nb-cells';
    scroll.appendChild(elCells);
    root.appendChild(scroll);

    // toolbar handlers
    btnRun.onclick = function () { const c = selectedCell || cells[0]; if (c) runCell(c); };
    btnRunAll.onclick = function () { runAll().catch(function (e) { alert('Run failed: ' + e.message); }); };
    btnInterrupt.onclick = function () { if (kernelId) NB.Kernels.interrupt(kernelId); };
    btnRestart.onclick = async function () {
      if (kernelId) {
        await NB.Kernels.restart(kernelId);
        for (const k of Object.keys(pending)) delete pending[k];
        for (const c of cells) { c.count = null; c.outputs = []; }
        renderAll();
      }
    };
    btnAddCode.onclick = function () { addCell('code'); };
    btnAddMd.onclick   = function () { addCell('markdown'); };
    btnSave.onclick    = function () { save().catch(function (e) { alert('Save failed: ' + e.message); }); };

    // Ctrl/Cmd+S
    document.addEventListener('keydown', kbSave);
  }

  function kbSave(e) {
    if (destroyed) { document.removeEventListener('keydown', kbSave); return; }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); save().catch(function () {}); }
  }

  // ---- load ----
  async function load() {
    buildDOM();
    try {
      const doc = await NB.Contents.get(path);
      const name = (doc.name || path).replace(/\.ipynb$/, '');
      notebookName = name;
      elName.textContent = name;
      hooks.onTitle && hooks.onTitle(name);
      const nb = doc.content || { cells: [] };
      cells = (nb.cells || []).map(function (c) {
        return {
          id: NB.uuid(),
          type: c.cell_type === 'markdown' ? 'markdown' : 'code',
          source: Array.isArray(c.source) ? c.source.join('') : (c.source || ''),
          outputs: [], count: c.execution_count != null ? c.execution_count : null,
          rendered: c.cell_type === 'markdown',
        };
      });
      if (cells.length === 0) addCell('code'); else renderAll();
      hooks.onLoaded && hooks.onLoaded();
      // auto-start the kernel as soon as the notebook opens (warm by the time
      // the user runs their first cell), instead of waiting for the first run.
      ensureKernel().catch(function () { setKernel('dead'); });
    } catch (e) {
      elCells.innerHTML = '<div class="output err">Failed to load notebook: ' + esc(e.message) + '</div>';
      hooks.onLoaded && hooks.onLoaded();
    }
  }

  function destroy() {
    destroyed = true;
    document.removeEventListener('keydown', kbSave);
    if (session) { try { session.close(); } catch (e) {} }
    root.innerHTML = '';
    root.className = '';
  }

  function setName(name) {
    notebookName = name;
    if (elName) elName.textContent = name;
  }

  load();

  return { destroy: destroy, save: save, exportAs: exportAs, setName: setName, getName: function () { return notebookName; } };
};
