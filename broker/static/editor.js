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
