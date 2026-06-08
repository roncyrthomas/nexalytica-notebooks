"""Nexalytica Notebooks - multi-user, no-iframe variation.

Auth (register/login) + per-user notebooks + a reverse proxy that serves each
notebook full-page at /nb/<uuid>/ (no iframe). Concurrent browsers are
independent users.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import auth
import nbfmt
import proxy
from usercontainers import UserContainerManager

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
manager: UserContainerManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global manager
    auth.init_db()
    manager = UserContainerManager()
    manager.start_reaper()
    yield
    await proxy.aclose()
    manager.shutdown()


app = FastAPI(title="Nexalytica Notebooks (multi-user)", lifespan=lifespan)


# ----- models ----------------------------------------------------------------
class Creds(BaseModel):
    email: str
    password: str


class CreateBody(BaseModel):
    name: str = "Untitled notebook"
    theme: str = "Nexalytica Default Dark"


class RenameBody(BaseModel):
    name: str


# ----- auth helpers ----------------------------------------------------------
def _uid(request: Request) -> str | None:
    return auth.read_session(request.cookies.get(auth.COOKIE_NAME))


def _require(request: Request) -> str:
    uid = _uid(request)
    if not uid:
        raise HTTPException(401, "not authenticated")
    return uid


def _set_cookie(resp, uid: str):
    resp.set_cookie(auth.COOKIE_NAME, auth.make_session(uid), httponly=True,
                    samesite="lax", max_age=auth.SESSION_TTL, path="/")


# ----- container helpers -----------------------------------------------------
async def _ensure_user_container(uid: str):
    u = await run_in_threadpool(auth.get_user_full, uid)
    if not u:
        raise HTTPException(401, "not authenticated")
    await run_in_threadpool(manager.ensure_running, uid,
                            u["container_key"], u["volume"])
    manager.touch(uid)
    return manager.target(uid)


def _container_base(uid: str) -> str:
    u = auth.get_user_full(uid)
    return f"u/{u['container_key']}"


def _sync_ensure(uid: str):
    u = auth.get_user_full(uid)
    if u:
        manager.ensure_running(uid, u["container_key"], u["volume"])
        manager.touch(uid)


# ----- pages -----------------------------------------------------------------
@app.get("/")
def index(request: Request):
    if not _uid(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/n/{uuid}")
def shell_for_notebook(request: Request, uuid: str):
    # Refresh-safe per-notebook URL; the shell reads the uuid and opens it.
    if not _uid(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/login")
def login_page(request: Request):
    if _uid(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/register")
def register_page(request: Request):
    if _uid(request):
        return RedirectResponse("/", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "register.html"))


@app.get("/e/{nid}")
def editor_page(request: Request, nid: str):
    if not _uid(request):
        return RedirectResponse("/login", status_code=302)
    return FileResponse(os.path.join(STATIC_DIR, "editor.html"))


# ----- auth API --------------------------------------------------------------
@app.post("/api/auth/register")
def register(body: Creds):
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 6:
        raise HTTPException(400, "valid email and 6+ char password required")
    uid = auth.create_user(email, body.password)
    if not uid:
        raise HTTPException(409, "an account with that email already exists")
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, uid)
    return resp


@app.post("/api/auth/login")
def login(body: Creds):
    uid = auth.authenticate(body.email, body.password)
    if not uid:
        raise HTTPException(401, "invalid email or password")
    resp = JSONResponse({"ok": True})
    _set_cookie(resp, uid)
    return resp


@app.post("/api/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
def me(request: Request):
    uid = _require(request)
    u = auth.get_user(uid)
    if not u:
        raise HTTPException(401, "not authenticated")
    return {"id": u["id"], "email": u["email"]}


# ----- notebook API ----------------------------------------------------------
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
    u = await run_in_threadpool(auth.get_user_full, uid)
    await proxy.put_json(f"u/{u['container_key']}/api/contents/{nb['path']}",
                         tgt["port"], tgt["token"],
                         {"type": "notebook", "content": nbfmt.empty_notebook()})
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


# ----- /api/nb proxy (HTTP + WS) ---------------------------------------------
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


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
