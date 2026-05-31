"""Docker-backed notebook session manager.

Each "notebook" is a persistent Docker volume + a transient container:
  * Compute is ephemeral  -> the container is created on open, removed on close.
  * Files persist         -> the volume (mounted at ~/work) survives close.
  * Opens are fast        -> a small warm pool of pre-started containers.

A small JSON registry persists notebook metadata (id, name, theme, volume) so
the explorer list survives a broker restart; reopening starts a fresh container
on the saved volume.
"""
import json
import os
import secrets
import socket
import threading
import time
import urllib.request

import docker

IMAGE = os.environ.get("NEX_IMAGE", "nexalytica-notebook")
POOL_SIZE = int(os.environ.get("NEX_POOL_SIZE", "2"))
NB_PORT = 8888
LABEL = {"nexalytica.broker": "1"}
NOTEBOOK_PATH = "/notebooks/work/Welcome.ipynb"
THEME_PLUGIN = "@jupyterlab/apputils-extension:themes"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REGISTRY_PATH = os.path.join(DATA_DIR, "registry.json")

VALID_THEMES = {
    "Nexalytica Default Dark", "Nexalytica Default Light",
    "Nexalytica Violet Dark", "Nexalytica Violet Light",
    "Nexalytica Sky Dark", "Nexalytica Sky Light",
    "Nexalytica Monochrome Dark", "Nexalytica Monochrome Light",
}


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class NotebookManager:
    def __init__(self):
        self.client = docker.from_env()
        self.sessions = {}          # sid -> session dict
        self.pool = []              # ready {container, volume, port, token}
        self.lock = threading.RLock()
        os.makedirs(DATA_DIR, exist_ok=True)
        self._load_registry()
        threading.Thread(target=self._fill_pool, daemon=True).start()

    # ----- persistence -------------------------------------------------------
    def _load_registry(self):
        try:
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = []
        for r in rows:
            self.sessions[r["id"]] = {
                "id": r["id"], "name": r["name"], "theme": r.get("theme", "Nexalytica Default Dark"),
                "volume": r["volume"], "status": "stopped", "url": None,
                "container": None, "port": None, "token": None,
            }

    def _save_registry(self):
        rows = [{"id": s["id"], "name": s["name"], "theme": s["theme"], "volume": s["volume"]}
                for s in self.sessions.values()]
        tmp = REGISTRY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        os.replace(tmp, REGISTRY_PATH)

    # ----- container lifecycle ----------------------------------------------
    def _start_container(self, volume, token, port):
        return self.client.containers.run(
            IMAGE, detach=True,
            environment={"JUPYTER_TOKEN": token},
            ports={f"{NB_PORT}/tcp": port},
            volumes={volume: {"bind": "/home/jovyan/work", "mode": "rw"}},
            labels=LABEL,
        )

    def _wait_ready(self, port, token, timeout=60):
        url = f"http://localhost:{port}/api?token={token}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    def _warm_one(self):
        volume = f"nex-{secrets.token_hex(6)}"
        self.client.volumes.create(name=volume, labels=LABEL)
        token = secrets.token_hex(16)
        port = _free_port()
        container = self._start_container(volume, token, port)
        if not self._wait_ready(port, token):
            raise RuntimeError("notebook container did not become ready")
        return {"container": container, "volume": volume, "port": port, "token": token}

    def _fill_pool(self):
        while True:
            with self.lock:
                need = POOL_SIZE - len(self.pool)
            if need <= 0:
                return
            try:
                ready = self._warm_one()
            except Exception:
                return
            with self.lock:
                self.pool.append(ready)

    def _set_theme(self, port, token, theme):
        if theme not in VALID_THEMES:
            return
        body = json.dumps({"raw": json.dumps({"theme": theme})}).encode()
        url = f"http://localhost:{port}/lab/api/settings/{THEME_PLUGIN}"
        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Authorization", f"token {token}")
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    # ----- public API --------------------------------------------------------
    def _public(self, s):
        return {"id": s["id"], "name": s["name"], "theme": s["theme"],
                "status": s["status"], "url": s.get("url")}

    def _bind_running(self, s, slot, theme):
        self._set_theme(slot["port"], slot["token"], theme)
        s.update(container=slot["container"], volume=slot["volume"],
                 port=slot["port"], token=slot["token"], theme=theme, status="running",
                 url=f"http://localhost:{slot['port']}{NOTEBOOK_PATH}?token={slot['token']}")

    def create_notebook(self, name, theme):
        with self.lock:
            slot = self.pool.pop(0) if self.pool else None
        if slot is None:
            slot = self._warm_one()
        sid = secrets.token_hex(8)
        session = {"id": sid, "name": name, "theme": theme, "status": "stopped",
                   "volume": slot["volume"], "container": None}
        self._bind_running(session, slot, theme)
        with self.lock:
            self.sessions[sid] = session
            self._save_registry()
        threading.Thread(target=self._fill_pool, daemon=True).start()
        return self._public(session)

    def open_notebook(self, sid, theme):
        with self.lock:
            s = self.sessions.get(sid)
        if not s:
            raise KeyError(sid)
        if s["status"] == "running":
            self._set_theme(s["port"], s["token"], theme)
            s["theme"] = theme
        else:
            token = secrets.token_hex(16)
            port = _free_port()
            container = self._start_container(s["volume"], token, port)
            if not self._wait_ready(port, token):
                raise RuntimeError("notebook container did not become ready")
            self._bind_running(s, {"container": container, "volume": s["volume"],
                                   "port": port, "token": token}, theme)
        with self.lock:
            self._save_registry()
        return self._public(s)

    def close_notebook(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
        if not s:
            raise KeyError(sid)
        c = s.get("container")
        if c is not None:
            try:
                c.remove(force=True)
            except Exception:
                pass
        s.update(container=None, status="stopped", url=None, port=None, token=None)
        return self._public(s)

    def rename_notebook(self, sid, name):
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                raise KeyError(sid)
            s["name"] = name.strip() or s["name"]
            self._save_registry()
            return self._public(s)

    def duplicate_notebook(self, sid):
        with self.lock:
            src = self.sessions.get(sid)
        if not src:
            raise KeyError(sid)
        new_vol = f"nex-{secrets.token_hex(6)}"
        self.client.volumes.create(name=new_vol, labels=LABEL)
        # copy files from the source volume into the new one (root, then chown)
        self.client.containers.run(
            IMAGE, remove=True, user="root",
            command=["bash", "-lc", "cp -a /from/. /to/ 2>/dev/null; chown -R 1000:100 /to"],
            volumes={src["volume"]: {"bind": "/from", "mode": "ro"},
                     new_vol: {"bind": "/to", "mode": "rw"}},
        )
        nid = secrets.token_hex(8)
        session = {"id": nid, "name": f"{src['name']} copy", "theme": src["theme"],
                   "volume": new_vol, "status": "stopped", "url": None,
                   "container": None, "port": None, "token": None}
        with self.lock:
            self.sessions[nid] = session
            self._save_registry()
        return self._public(session)

    def delete_notebook(self, sid):
        with self.lock:
            s = self.sessions.pop(sid, None)
        if not s:
            raise KeyError(sid)
        c = s.get("container")
        if c is not None:
            try:
                c.remove(force=True)
            except Exception:
                pass
        try:
            self.client.volumes.get(s["volume"]).remove(force=True)
        except Exception:
            pass
        with self.lock:
            self._save_registry()
        return {"id": sid, "deleted": True}

    def list_notebooks(self):
        with self.lock:
            return [self._public(s) for s in self.sessions.values()]

    def shutdown(self):
        with self.lock:
            items = list(self.sessions.values()) + self.pool
        for it in items:
            c = it.get("container")
            if c is not None:
                try:
                    c.remove(force=True)
                except Exception:
                    pass
