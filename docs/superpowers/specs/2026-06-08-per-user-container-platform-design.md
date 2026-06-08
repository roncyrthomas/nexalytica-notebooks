# Per-User Container Platform + Custom Notebook UI — Design

**Date:** 2026-06-08
**Status:** Approved for planning
**Branch:** `multiuser-direct`

---

## 1. Problem & Goals

Today the platform runs **one Docker container per notebook** (`broker/manager.py`). Each
notebook gets its own container, volume, token, and `/nb/<uuid>/` route, with a warm pool
for instant open. This does not scale to tens of thousands of users — container count grows
with notebook count, not user count.

**Primary goal:** move to **one container per user**, where a user's notebooks are files
inside that single container, provisioned on demand and reaped when idle.

**Secondary goal (security, hard requirement):** a user has terminal/code access inside their
container, so the container must hold **no secret that grants access to anything beyond that
user's own sandbox** — no DB credentials, no platform secrets. The production database must be
unreachable from any user container.

**Tertiary goal:** replace exposed JupyterLab with our **own notebook UI** (Option C) that
talks to the Jupyter REST/WS API through the broker. No Lab, no exposed terminal.

### Success criteria
- A user with many notebooks consumes **one** container, not N.
- Idle containers are stopped after **1 hour**; orphaned containers are reaped.
- Each container is capped at **0.5 CPU / 1 GB RAM** (tier-adjustable later).
- A container can reach the internet but **cannot reach other containers or the host DB**.
- The browser never receives a Jupyter token or a raw container port.
- A working "Core" custom notebook editor: code+markdown cells, run/run-all,
  add/delete/reorder, common output types, save/load, kernel restart/interrupt.

---

## 2. Non-Goals (explicitly deferred)

- **Real-time collaboration** (the current RTC work) — may lapse during this migration.
- **Notebook sharing / RBAC** — future sub-project; design must not preclude it.
- **UI beyond "Core"** — no autocomplete, file sidebar, multi-notebook tabs, ipywidgets,
  rich mimetypes (LaTeX/Vega), variable inspector, debugger. These are later phases.
- **Warm pool** — dropped for the per-user model (see §4.3). Revisit later if cold-start hurts.
- **Per-notebook compute isolation** — accepted trade-off; one user's notebooks share one
  kernel host. (Per-notebook isolation would need Firecracker-class VMs.)

---

## 3. Architecture

Three layers; the **only** trust boundary is the broker.

```
Browser — custom React UI (CodeMirror 6 + @jupyterlab/services)
   │   cookie-authenticated REST + WebSocket
   │   NO Jupyter token, NO raw container port ever sent to the client
   ▼
Broker (FastAPI)  — auth · per-user routing · reverse proxy · lifecycle/reaping
   │   injects per-user Jupyter token server-side; dials 127.0.0.1:<port>
   ▼
Per-user container — headless jupyter-server (no Lab, terminals disabled)
                     mounts only the user's named volume at /home/jovyan/work
```

Sub-systems specced here:
1. **Runtime** — `manager.py` rewrite: per-user lifecycle, reapers, limits, network isolation.
2. **Broker API** — `app.py` + `proxy.py`: authenticated proxy over contents + kernels + kernel WS.
3. **Custom UI** — new frontend, "Core" scope.

---

## 4. Sub-system 1 — Per-User Container Runtime

### 4.1 Identity & data model

Each **user** owns exactly one container and one named volume.

- `users.container_key` — random `secrets.token_hex(16)`; the routing/base_url identity.
  Unguessable, decoupled from email/uid. Used as Jupyter `base_url = /u/<container_key>/`.
- `users.volume` — named Docker volume `nex-vol-<uid>`, created on first provision,
  mounted at `/home/jovyan/work`. Persists across container stop/start.
- A **notebook** is a row pointing at a file path inside that volume:
  `notebooks(id, user_id, name, theme, path, created)` where `path = work/<id>.ipynb`.

Runtime (in-memory, broker process): `user_id -> {container, port, token, last_active}`.

### 4.2 Lifecycle

- **Provision/reuse (on open):** when a user opens any notebook, the broker checks the
  in-memory runtime table; if a healthy container exists, reuse it and bump `last_active`.
  Otherwise start one with the user's volume, wait until the Jupyter API answers, register it.
- **Cold start** is accepted (~3–4 s per the existing perf work); subsequent opens are instant.
- **Token** is freshly generated per container start (`secrets.token_hex(16)`), kept only in
  the broker's runtime table. Never persisted, never sent to the browser.
- **Idle reaper:** background thread; every container with
  `now - last_active > 3600 s` is stopped and removed (volume kept). `last_active` is bumped
  on any proxied request/WS activity for that user.
- **Orphan reaper:** on broker startup and periodically, list containers by label
  `nexalytica.broker=1` and remove any not present in the runtime table (left over from a
  crash/restart). Volumes are never auto-removed by the reaper — only on explicit account/
  notebook deletion paths.

### 4.3 Why no warm pool

A warm container must mount the *user's* named volume at start; you cannot remount a volume
into an already-running container. A generic pre-booted pool therefore cannot become a specific
user's container without restart, which defeats the purpose. We rely on fast boot instead and
revisit if cold-start latency proves painful.

### 4.4 Resource limits

Containers are started with (Docker SDK `containers.run`):
- `nano_cpus = 500_000_000` (0.5 CPU)
- `mem_limit = "1g"`, `memswap_limit = "1g"` (no swap headroom beyond RAM cap)
- `pids_limit` set to a sane cap (e.g. 256) to blunt fork bombs.

These become tier-driven later; for now constants in config.

### 4.5 Network isolation

- All user containers join a dedicated Docker bridge network created with
  **inter-container communication disabled** (`com.docker.network.bridge.enable_icc=false`),
  so containers cannot talk to each other.
- Internet egress remains allowed (no special config needed on a normal bridge).
- The **production DB is not on this network** and is not reachable from it. The broker talks
  to the DB; containers never do.
- The container's Jupyter port is published to **`127.0.0.1:<random>`** only (host-loopback),
  reachable by the broker, not externally. (Internal-only networking via the bridge is a
  possible later hardening; deferred per team decision to keep it simple.)

### 4.6 Zero-secret container (security core)

- The container's environment contains **only** `JUPYTER_TOKEN` (that container's own,
  single-tenant token) plus stock Jupyter vars. No DB URL, no API keys, no platform secrets.
- The container is started with terminals disabled and Lab not used (see §5/§6), reducing
  the attack surface; even so the security model does **not** rely on hiding the terminal —
  it relies on there being nothing valuable in the container to steal and nothing valuable
  reachable from it.
- Hardening flags on `start-notebook.py` / `jupyter server`:
  `--ServerApp.terminals_enabled=False`, `--ServerApp.root_dir=/home/jovyan/work`,
  existing `--ServerApp.disable_check_xsrf=True --ServerApp.allow_origin=*` retained
  (the broker is the only origin that reaches it).

---

## 5. Sub-system 2 — Broker API Contract

The broker exposes a **cookie-authenticated** surface; every request resolves the session
cookie → `user_id` → that user's container, then proxies to the container's Jupyter API with
the server-side token injected. The browser sees neither token nor port.

### 5.1 Auth & routing
- Session cookie (existing `auth.read_session`) → `user_id`.
- Helper `ensure_container(user_id)` returns `{port, token}`, starting the container if needed
  and bumping `last_active`.
- All notebook IDs in requests are verified to belong to `user_id` (existing ownership check
  pattern) before any path is constructed.

### 5.2 Endpoints (browser ↔ broker)
REST (JSON), all under `/api/nb/...`, all proxied to the user's container:
- **Contents** — list/read/write/rename/delete files under the user's volume, scoped to
  `work/`. Maps notebook `id` → `path`. Backed by Jupyter `/api/contents`.
- **Sessions/Kernels** — start/list/interrupt/restart/delete kernels. Backed by Jupyter
  `/api/sessions` and `/api/kernels`.
- **Kernelspecs** — read-only, to show the kernel name.

WebSocket:
- **Kernel channels** — `/api/nb/kernel/{kernel_id}/channels` proxied to the container's
  `/api/kernels/{id}/channels` (the execute/iopub channel). This is the live execution path,
  reusing the existing `proxy.proxy_ws` machinery (wsproto) with token injection.

### 5.3 Proxy behavior
- Reuse the pooled streaming HTTP client and WS proxy from the recent perf work.
- Inject `Authorization: token <token>` server-side on every upstream call.
- Path rewriting: browser-facing `/api/nb/...` ↔ upstream `/u/<container_key>/api/...`.

---

## 6. Sub-system 3 — Custom Notebook UI ("Core")

### 6.1 Stack
- **React** SPA (served by the broker as static assets, like today's `static/`).
- **`@jupyterlab/services`** — the official JS client for the Jupyter REST/WS protocol.
  Configured with `baseUrl` = the broker's `/api/nb/` surface and **no token** (the broker
  injects it). We do **not** hand-roll the kernel message protocol.
- **CodeMirror 6** — cell editor (Python mode).
- Output rendering: lightweight in-house renderers for the Core mimetypes (see §6.4).
  (Evaluate `@jupyterlab/rendermime` vs hand-rolled during planning; default hand-rolled for
  the four Core types to avoid pulling in Lab weight.)

### 6.2 Component architecture
- `NotebookApp` — owns the open notebook + kernel connection (`@jupyterlab/services`
  `KernelManager`/`SessionManager`), toolbar actions, save state.
- `CellList` — ordered cells; add/delete/reorder.
- `Cell` — `CodeCell` | `MarkdownCell`. Code cell holds a CodeMirror instance + `OutputArea`.
- `OutputArea` — renders the cell's output list.
- `KernelStatus` — status pill (idle/busy/starting/dead) + restart/interrupt.
- `Toolbar` — Run, Run all, Interrupt, Restart, +Code, +Markdown, Save.

### 6.3 Data flow
- **Load:** fetch `.ipynb` JSON via contents API → parse `nbformat` cells into component state.
- **Execute:** ensure a kernel/session for the notebook → `kernel.requestExecute({code})` →
  stream replies (`stream`, `execute_result`, `display_data`, `error`,
  `execute_input`/`status` for the `[n]` counter and busy state) → append to the cell's outputs.
- **Save:** serialize cell state → valid `nbformat` JSON → contents API `PUT`. Autosave on a
  debounce + explicit ⌘S; show "saved" state.

### 6.4 Output rendering (Core)
Render these mimetypes; ignore others gracefully (show a "[unsupported output]" placeholder):
- `text/plain` and stream stdout/stderr (monospace, stderr tinted).
- `text/html` (pandas tables etc.) — sanitized before injection.
- `image/png` / `image/jpeg` — `<img src=data:...>`.
- `error` — traceback with ANSI stripped/converted, red treatment.

### 6.5 Error handling (UI)
- Kernel dead/restart → status pill reflects it; offer restart.
- Container starting / 502 from broker → cell/run shows a "starting kernel…" state, retries.
- WS drop → auto-reconnect via `@jupyterlab/services` defaults; surface a banner if it fails.
- HTML output is sanitized to prevent stored XSS from notebook content.

---

## 7. Data Model & Migration

### 7.1 Schema changes (`auth.py`, SQLite)
- `users`: add `container_key TEXT`, `volume TEXT`.
- `notebooks`: replace per-notebook `volume`, `secret` with `path TEXT`
  (`work/<id>.ipynb`). Keep `id, user_id, name, theme, created`.

### 7.2 Migration of existing data
**Decision: start clean (reset).** Pre-prod data is disposable. On rollout:
- Drop the old `notebooks` rows and recreate the table with the new schema.
- Remove all existing broker-labelled containers and per-notebook volumes
  (`nexalytica.broker=1`), so no orphaned per-notebook artifacts remain.
- Users keep their accounts; their notebook list starts empty under the new per-user model.
No copy/migration of old `.ipynb` content is performed.

---

## 8. Testing Strategy

- **Unit (pytest):** lifecycle logic (provision/reuse/idle decision), data-model helpers,
  path mapping (`id` ↔ `work/<id>.ipynb`), ownership checks. Mock the Docker SDK.
- **Integration:** broker API against a real per-user container — contents CRUD, kernel
  start, execute-over-WS round trip, idle reap, orphan reap.
- **Security tests (must pass before deploy):**
  - container env contains no secret beyond `JUPYTER_TOKEN`;
  - a code cell cannot open a socket to another user's container;
  - a code cell cannot reach the production DB host;
  - the browser is never sent the token or the container port (inspect responses).
- **UI:** component tests for cell ops + output rendering; one E2E (Playwright) — create
  notebook, run a cell, see output, save, reload, restart kernel.
- Target 80%+ coverage on broker logic per project standard.

---

## 9. Risks & Open Questions

- **Path-rewriting fidelity** for the contents/kernels proxy — the main implementation risk;
  validated early in the plan with a thin proxy spike.
- **`@jupyterlab/services` baseUrl/token wiring** through a token-stripping proxy — confirm the
  client tolerates an empty token when the proxy injects it.
- **Migration choice** (§7.2) — needs a team decision (migrate vs reset).
- **ICC-disabled bridge on the deployment host** — confirm the prod Docker daemon allows the
  custom network options.
- **Custom UI is a large build** — Core is the MVP; productivity/parity features are later
  sub-projects and must not block the per-user migration shipping.

---

## 10. Build Order (high level — detailed plan follows)

1. Runtime rewrite (per-user lifecycle + limits + network + reapers) behind the existing Lab,
   to de-risk the backend independent of the new UI.
2. Broker API contract (contents/kernels/WS proxy, token-stripped, cookie-auth).
3. Custom Core UI against that contract.
4. Migration + security test gate, then cut over.
