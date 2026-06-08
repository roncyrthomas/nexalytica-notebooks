# Broker API + Cutover — Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Cut the broker over from per-notebook containers to the per-user `UserContainerManager`, change the data model to per-user volumes + file-path notebooks, and expose one authenticated proxy surface (`/api/nb/...`) over the user's container's Jupyter REST + kernel-WS — the contract the custom UI (Plan 3) consumes.

**Architecture:** `auth.py` gets per-user `container_key`/`volume` and notebook `path`. `proxy.py` is generalized to proxy an arbitrary upstream path (not just `/nb/<uuid>/`). `app.py` drops the old `NotebookManager` and per-notebook routes, wires `UserContainerManager` (+ reaper), and adds: notebook CRUD (files in the user's container) and a catch-all HTTP+WS proxy under `/api/nb/`. A `reset.py` performs the start-clean wipe.

**Tech Stack:** FastAPI, Starlette, httpx, wsproto/websockets, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-per-user-container-platform-design.md` (§5 API, §7 data model).

**Depends on:** Plan 1 (`config.py`, `docker_ops.py`, `usercontainers.py` — present and tested).

---

## File Structure
- Modify: `broker/auth.py` — schema + accessors (per-user container_key/volume; notebook path).
- Modify: `broker/usercontainers.py` — `ensure_running` creates the volume if missing.
- Modify: `broker/proxy.py` — route-agnostic `proxy_http`/`proxy_ws` (arbitrary upstream path).
- Modify: `broker/app.py` — wire UserContainerManager, notebook CRUD, `/api/nb` proxy.
- Create: `broker/nbfmt.py` — empty-notebook nbformat skeleton helper.
- Create: `broker/reset.py` — start-clean wipe (DB + labelled containers/volumes).
- Tests: `broker/tests/test_auth_schema.py`, `broker/tests/test_proxy_paths.py`, `broker/tests/test_nbfmt.py`, extend `broker/tests/test_usercontainers.py`.

---

## Task 1: auth.py — per-user schema + accessors

**Files:** Modify `broker/auth.py`; Test `broker/tests/test_auth_schema.py`.

- [ ] **Step 1: Failing test** — `broker/tests/test_auth_schema.py`

```python
import os
import tempfile

import auth


def _fresh_db(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth, "DB_PATH", os.path.join(str(tmp_path), "app.db"))
    auth.init_db()


def test_create_user_assigns_container_key_and_volume(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    uid = auth.create_user("a@b.com", "secret1")
    u = auth.get_user_full(uid)
    assert u["container_key"] and len(u["container_key"]) >= 16
    assert u["volume"] == f"nex-vol-{uid}"


def test_notebook_row_has_path_not_volume(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    uid = auth.create_user("a@b.com", "secret1")
    nb = auth.create_notebook_row(uid, "My NB", "Nexalytica Default Dark")
    assert nb["path"] == f"{nb['id']}.ipynb"
    assert "volume" not in nb and "secret" not in nb
    got = auth.get_notebook(nb["id"])
    assert got["path"] == nb["path"] and got["user_id"] == uid
```

- [ ] **Step 2: Run — expect FAIL** (`get_user_full` missing / schema mismatch)

Run: `cd broker && python -m pytest tests/test_auth_schema.py -q`

- [ ] **Step 3: Edit `broker/auth.py`**

In `init_db()` replace the two `CREATE TABLE` statements with:
```python
        c.execute("CREATE TABLE IF NOT EXISTS users ("
                  "id TEXT PRIMARY KEY, email TEXT UNIQUE, pw TEXT, "
                  "container_key TEXT, volume TEXT, created REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS notebooks ("
                  "id TEXT PRIMARY KEY, user_id TEXT, name TEXT, theme TEXT, "
                  "path TEXT, created REAL)")
```

Replace `create_user` with:
```python
def create_user(email: str, pw: str) -> str | None:
    uid = secrets.token_hex(8)
    container_key = secrets.token_hex(16)
    volume = f"nex-vol-{uid}"
    with _lock, _db() as c:
        try:
            c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                      (uid, email.lower().strip(), hash_pw(pw),
                       container_key, volume, time.time()))
        except sqlite3.IntegrityError:
            return None
    return uid
```

Add accessor (after `get_user`):
```python
def get_user_full(uid: str):
    with _db() as c:
        row = c.execute("SELECT id, email, container_key, volume FROM users "
                        "WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None
```

Replace `create_notebook_row` with:
```python
def create_notebook_row(user_id: str, name: str, theme: str,
                        nid: str | None = None) -> dict:
    nid = nid or secrets.token_hex(8)
    path = f"{nid}.ipynb"
    with _lock, _db() as c:
        c.execute("INSERT INTO notebooks VALUES (?,?,?,?,?,?)",
                  (nid, user_id, name, theme, path, time.time()))
    return {"id": nid, "user_id": user_id, "name": name, "theme": theme,
            "path": path}
```

(Leave `list_notebooks`, `get_notebook`, `rename_notebook`, `delete_notebook_row`,
sessions, passwords unchanged — they `SELECT *` / operate by id so they keep working.)

- [ ] **Step 4: Run — expect PASS (2 passed)**

Run: `cd broker && python -m pytest tests/test_auth_schema.py -q`

- [ ] **Step 5: Commit**

```bash
git add broker/auth.py tests/test_auth_schema.py
git commit -m "feat(api): per-user container_key/volume + notebook path schema"
```

---

## Task 2: usercontainers — create volume on demand

**Files:** Modify `broker/usercontainers.py`; Test: extend `broker/tests/test_usercontainers.py`.

- [ ] **Step 1: Failing test** (append to `broker/tests/test_usercontainers.py`)

```python
def test_ensure_running_creates_volume(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    fake_ops.create_volume.assert_called_once_with("nex-vol-u1")
```

- [ ] **Step 2: Run — expect FAIL** (`create_volume` not called)

Run: `cd broker && python -m pytest tests/test_usercontainers.py -k create_volume -q`

- [ ] **Step 3: Edit `ensure_running`** — in `broker/usercontainers.py`, inside the slow-path
(after `token`/`port` are computed, immediately before `self.ops.run_container(...)`), add:
```python
            self.ops.create_volume(volume)
```

- [ ] **Step 4: Run full suite — expect PASS (21 passed)**

Run: `cd broker && python -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add broker/usercontainers.py tests/test_usercontainers.py
git commit -m "feat(runtime): ensure_running provisions the user volume"
```

---

## Task 3: nbfmt.py — empty notebook skeleton

**Files:** Create `broker/nbfmt.py`; Test `broker/tests/test_nbfmt.py`.

- [ ] **Step 1: Failing test** — `broker/tests/test_nbfmt.py`

```python
import nbfmt


def test_empty_notebook_is_valid_nbformat_v4():
    nb = nbfmt.empty_notebook()
    assert nb["nbformat"] == 4
    assert nb["cells"] == []
    assert nb["metadata"]["kernelspec"]["name"] == "python3"
```

- [ ] **Step 2: Run — expect FAIL** (no module)

Run: `cd broker && python -m pytest tests/test_nbfmt.py -q`

- [ ] **Step 3: Create `broker/nbfmt.py`**

```python
"""Minimal nbformat v4 helpers (no nbformat dependency needed)."""


def empty_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3",
                           "language": "python"},
            "language_info": {"name": "python"},
        },
        "cells": [],
    }
```

- [ ] **Step 4: Run — expect PASS (1 passed)**

Run: `cd broker && python -m pytest tests/test_nbfmt.py -q`

- [ ] **Step 5: Commit**

```bash
git add broker/nbfmt.py tests/test_nbfmt.py
git commit -m "feat(api): empty nbformat v4 notebook helper"
```

---

## Task 4: proxy.py — route-agnostic proxying

Generalize the two proxy functions to forward to an arbitrary upstream path so the same code
serves `/api/nb/...` → `/u/<key>/...`. This is a pure refactor of signatures + target URL.

**Files:** Modify `broker/proxy.py`; Test `broker/tests/test_proxy_paths.py`.

- [ ] **Step 1: Failing test** — `broker/tests/test_proxy_paths.py`

```python
import proxy


def test_build_target_url_joins_and_keeps_query():
    url = proxy.build_target_url(40000, "u/key1/api/contents/x.ipynb", "a=1&b=2")
    assert url == "http://127.0.0.1:40000/u/key1/api/contents/x.ipynb?a=1&b=2"


def test_build_target_url_no_query():
    url = proxy.build_target_url(40000, "u/key1/api/kernels", "")
    assert url == "http://127.0.0.1:40000/u/key1/api/kernels"


def test_build_ws_url_uses_ws_scheme():
    url = proxy.build_ws_url(40000, "u/key1/api/kernels/abc/channels", "session_id=z")
    assert url == "ws://127.0.0.1:40000/u/key1/api/kernels/abc/channels?session_id=z"
```

- [ ] **Step 2: Run — expect FAIL** (helpers missing)

Run: `cd broker && python -m pytest tests/test_proxy_paths.py -q`

- [ ] **Step 3: Edit `broker/proxy.py`**

Add near the top (after `_DROP_RESP`):
```python
def build_target_url(port: int, upstream_path: str, query: str) -> str:
    base = f"http://127.0.0.1:{port}/{upstream_path}"
    return f"{base}?{query}" if query else base


def build_ws_url(port: int, upstream_path: str, query: str) -> str:
    base = f"ws://127.0.0.1:{port}/{upstream_path}"
    return f"{base}?{query}" if query else base
```

Change `proxy_http` signature and target line to use the helper:
```python
async def proxy_http(request, upstream_path: str, port: int, token: str) -> Response:
    q = request.url.query
    target = build_target_url(port, upstream_path, q)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _DROP_REQ}
    headers["Authorization"] = f"token {token}"
    body = await request.body()
    client = _get_client()
    up_req = client.build_request(request.method, target, content=body, headers=headers)
    up = await client.send(up_req, stream=True, follow_redirects=False)
    out_headers = [(k, v) for k, v in up.headers.multi_items()
                   if k.lower() not in _DROP_RESP]

    async def body_stream():
        try:
            async for chunk in up.aiter_raw():
                yield chunk
        finally:
            await up.aclose()

    return StreamingResponse(body_stream(), status_code=up.status_code,
                             headers=dict(out_headers))
```

Change `proxy_ws` signature and target line:
```python
async def proxy_ws(websocket: WebSocket, upstream_path: str, port: int, token: str):
    proto = websocket.headers.get("sec-websocket-protocol")
    requested = [p.strip() for p in proto.split(",")] if proto else None
    qs = websocket.url.query
    target = build_ws_url(port, upstream_path, qs)
    upstream = None
    for _ in range(30):
        try:
            upstream = await websockets.connect(
                target, subprotocols=requested,
                additional_headers={"Authorization": f"token {token}"},
                max_size=None, open_timeout=20, ping_interval=None)
            break
        except Exception:
            await asyncio.sleep(0.5)
    if upstream is None:
        await websocket.accept(subprotocol=requested[0] if requested else None)
        await websocket.close(code=1011)
        return
    await websocket.accept(subprotocol=upstream.subprotocol)
    # (rest of the function — client_to_upstream / upstream_to_client / gather —
    #  is UNCHANGED from the current implementation)
```

Keep the two inner coroutines and the final `await asyncio.gather(...)` exactly as they are now.

- [ ] **Step 4: Run — expect PASS (3 passed)** and full suite green

Run: `cd broker && python -m pytest tests/test_proxy_paths.py -q && python -m pytest -q`

- [ ] **Step 5: Commit**

```bash
git add broker/proxy.py tests/test_proxy_paths.py
git commit -m "refactor(api): route-agnostic proxy_http/proxy_ws with URL builders"
```

---

## Task 5: app.py — wire UserContainerManager + lifespan

**Files:** Modify `broker/app.py`.

- [ ] **Step 1: Replace imports + lifespan + manager wiring**

In `broker/app.py`:
- Remove `from manager import NotebookManager`; add `from usercontainers import UserContainerManager` and `import nbfmt`.
- Replace the `lifespan` body:
```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    global manager
    auth.init_db()
    manager = UserContainerManager()
    manager.start_reaper()
    yield
    await proxy.aclose()
    manager.shutdown()
```
- Keep `manager: ... = None` annotation as `manager: UserContainerManager | None = None`.

- [ ] **Step 2: Add the per-user container helper** (after the auth helpers)

```python
async def _ensure_user_container(uid: str):
    u = await run_in_threadpool(auth.get_user_full, uid)
    if not u:
        raise HTTPException(401, "not authenticated")
    await run_in_threadpool(manager.ensure_running, uid,
                            u["container_key"], u["volume"])
    manager.touch(uid)
    return manager.target(uid)
```

- [ ] **Step 3: Verify the app imports** (no test yet; import smoke)

Run: `cd broker && python -c "import app; print('ok')"`
Expected: `ok` (no ImportError). If `docker.from_env()` errors at import, that's fine — it only runs in lifespan, not at import.

- [ ] **Step 4: Commit**

```bash
git add broker/app.py
git commit -m "feat(api): wire UserContainerManager + reaper into app lifespan"
```

---

## Task 6: app.py — notebook CRUD over the user's container

Notebooks are files in the user's container. Create/list/rename/delete operate on rows +
the contents API. No per-notebook open/close (container lifecycle is per-user/automatic).

**Files:** Modify `broker/app.py`.

- [ ] **Step 1: Replace the notebook API section**

Replace `_public`, the create/open/close/rename/delete handlers with:
```python
def _public(nb: dict) -> dict:
    return {"id": nb["id"], "name": nb["name"], "theme": nb["theme"],
            "path": nb["path"]}


@app.get("/api/notebooks")
def list_notebooks(request: Request):
    uid = _require(request)
    return [_public(nb) for nb in auth.list_notebooks(uid)]


@app.post("/api/notebooks")
async def create_notebook(request: Request, body: CreateBody):
    uid = _require(request)
    tgt = await _ensure_user_container(uid)
    nb = await run_in_threadpool(
        auth.create_notebook_row, uid, body.name.strip() or "Untitled notebook",
        body.theme)
    # write an empty notebook file into the user's container
    import json
    payload = json.dumps({"type": "notebook", "content": nbfmt.empty_notebook()})

    class _Body:
        method = "PUT"
        url = type("U", (), {"query": ""})()
        headers = {"content-type": "application/json"}
        async def body(self):
            return payload.encode()
    await proxy.proxy_http(_Body(), f"u/{(await run_in_threadpool(auth.get_user_full, uid))['container_key']}/api/contents/{nb['path']}",
                           tgt["port"], tgt["token"])
    return _public(nb)


@app.patch("/api/notebooks/{nid}")
def rename_notebook(request: Request, nid: str, body: RenameBody):
    uid = _require(request)
    if not auth.rename_notebook(nid, uid, body.name.strip()):
        raise HTTPException(404, "no such notebook")
    return _public(auth.get_notebook(nid))


@app.delete("/api/notebooks/{nid}")
async def delete_notebook(request: Request, nid: str):
    uid = _require(request)
    nb = auth.get_notebook(nid)
    if not nb or nb["user_id"] != uid:
        raise HTTPException(404, "no such notebook")
    auth.delete_notebook_row(nid, uid)
    return {"id": nid, "deleted": True}
```

NOTE: the `_Body` shim above is awkward. PREFER this cleaner approach instead — add a small
helper to `proxy.py` and call it:

In `broker/proxy.py` add:
```python
async def put_json(upstream_path: str, port: int, token: str, obj: dict):
    import json
    client = _get_client()
    r = await client.put(build_target_url(port, upstream_path, ""),
                         content=json.dumps(obj).encode(),
                         headers={"Authorization": f"token {token}",
                                  "Content-Type": "application/json"})
    return r
```

Then in `create_notebook` replace the `_Body`/`proxy_http` block with:
```python
    u = await run_in_threadpool(auth.get_user_full, uid)
    await proxy.put_json(f"u/{u['container_key']}/api/contents/{nb['path']}",
                         tgt["port"], tgt["token"],
                         {"type": "notebook", "content": nbfmt.empty_notebook()})
```
Use the `put_json` approach; delete the `_Body` shim entirely.

- [ ] **Step 2: Import smoke**

Run: `cd broker && python -c "import app; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add broker/app.py broker/proxy.py
git commit -m "feat(api): notebook CRUD as files in the user's container"
```

---

## Task 7: app.py — `/api/nb` proxy (HTTP + WS) and route cleanup

One authenticated catch-all that proxies everything the UI needs (contents, kernels,
sessions, kernelspecs, kernel channels WS) to the user's container.

**Files:** Modify `broker/app.py`.

- [ ] **Step 1: Remove old per-notebook proxy routes**

Delete `_authorize_and_target`, `nb_ws`, `nb_root_redirect`, `nb_http` (the `/nb/{uuid}/...`
routes) and the `/n/{uuid}` shell route's dependency on per-notebook running (keep `/n/{uuid}`
returning index for now; Plan 3 swaps the page). Remove the `ThemeBody`-based open/close.

- [ ] **Step 2: Add the `/api/nb` proxy** (place above `app.mount("/static", ...)`)

```python
def _container_base(uid: str) -> str:
    u = auth.get_user_full(uid)
    return f"u/{u['container_key']}"


@app.websocket("/api/nb/{path:path}")
async def nb_api_ws(websocket: WebSocket, path: str):
    uid = auth.read_session(websocket.cookies.get(auth.COOKIE_NAME))
    if not uid:
        await websocket.close(code=1008)
        return
    await run_in_threadpool(_sync_ensure, uid)
    tgt = manager.target(uid)
    if not tgt:
        await websocket.close(code=1011)
        return
    base = await run_in_threadpool(_container_base, uid)
    await proxy.proxy_ws(websocket, f"{base}/{path}", tgt["port"], tgt["token"])


@app.api_route("/api/nb/{path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def nb_api_http(request: Request, path: str):
    uid = _require(request)
    tgt = await _ensure_user_container(uid)
    base = await run_in_threadpool(_container_base, uid)
    return await proxy.proxy_http(request, f"{base}/{path}", tgt["port"], tgt["token"])
```

Add the sync helper used by the WS path (near `_ensure_user_container`):
```python
def _sync_ensure(uid: str):
    u = auth.get_user_full(uid)
    if u:
        manager.ensure_running(uid, u["container_key"], u["volume"])
        manager.touch(uid)
```

- [ ] **Step 3: Import smoke + full unit suite**

Run: `cd broker && python -c "import app; print('ok')" && python -m pytest -q`
Expected: `ok`; unit tests still green (no app integration tests run without Docker).

- [ ] **Step 4: Commit**

```bash
git add broker/app.py
git commit -m "feat(api): authenticated /api/nb proxy (HTTP+WS) to the user's container"
```

---

## Task 8: reset.py — start-clean wipe

**Files:** Create `broker/reset.py`.

- [ ] **Step 1: Create `broker/reset.py`**

```python
"""Start-clean reset for the per-user migration. DESTRUCTIVE.

Removes the SQLite DB and every broker-labelled container AND volume (old
per-notebook artifacts included). Users must re-register; notebooks start empty.

    cd broker && python reset.py --yes
"""
import os
import sys

import docker

import auth
import config


def reset(confirm: bool):
    if not confirm:
        print("Refusing to reset without --yes")
        return 1
    # 1) DB
    try:
        os.remove(auth.DB_PATH)
        print(f"removed {auth.DB_PATH}")
    except FileNotFoundError:
        pass
    # 2) containers + volumes by label
    client = docker.from_env()
    for c in client.containers.list(all=True,
                                    filters={"label": f"{config.LABEL_KEY}=1"}):
        try:
            c.remove(force=True)
            print(f"removed container {c.name}")
        except Exception as e:
            print(f"container {c.name}: {e}")
    for v in client.volumes.list(filters={"label": f"{config.LABEL_KEY}=1"}):
        try:
            v.remove(force=True)
            print(f"removed volume {v.name}")
        except Exception as e:
            print(f"volume {v.name}: {e}")
    print("reset complete")
    return 0


if __name__ == "__main__":
    sys.exit(reset("--yes" in sys.argv))
```

- [ ] **Step 2: Smoke (no Docker needed for the guard path)**

Run: `cd broker && python reset.py`
Expected: prints `Refusing to reset without --yes` and exits non-zero. (Do NOT run with `--yes`
here unless you intend to wipe.)

- [ ] **Step 3: Commit**

```bash
git add broker/reset.py
git commit -m "feat(ops): start-clean reset (DB + labelled containers/volumes)"
```

---

## Task 9: Remove the dead per-notebook manager

**Files:** Delete `broker/manager.py` (replaced by `usercontainers.py`).

- [ ] **Step 1: Confirm nothing imports it**

Run: `cd broker && grep -rn "from manager import\|import manager" . --include=*.py || echo "no refs"`
Expected: `no refs` (Task 5 removed the import).

- [ ] **Step 2: Delete + verify app still imports**

```bash
git rm broker/manager.py
cd broker && python -c "import app; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(api): drop dead per-notebook manager"
```

---

## Plan-vs-Spec Self-Review
- §5.1 auth/routing → Tasks 5,7 (`_ensure_user_container`, `/api/nb`). ✓
- §5.2 contents/kernels/sessions/kernelspecs/WS → single `/api/nb/{path}` catch-all (Task 7) covers all. ✓
- §5.3 token injection + path rewrite → Task 4 helpers + Task 7. ✓
- §7.1 schema → Task 1. §7.2 reset → Task 8. ✓
- §4.1 volume provisioning → Task 2. ✓
- Placeholder scan: the `_Body` shim in Task 6 is explicitly replaced by `put_json` — implement the `put_json` path. ✓

## Handoff to Plan 3
The browser-facing contract is now: cookie auth; `GET/POST/PATCH/DELETE /api/notebooks`;
and a Jupyter server reachable at base `/api/nb/` (so contents = `/api/nb/api/contents/<id>.ipynb`,
kernels = `/api/nb/api/kernels`, channels WS = `/api/nb/api/kernels/<kid>/channels`). Plan 3
builds the vanilla-JS Core UI against exactly this.
