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
