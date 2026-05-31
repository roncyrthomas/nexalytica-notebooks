"""Per-notebook Docker runtime for the multi-user / no-iframe variation.

INSTANT OPEN via a warm pool: the broker keeps a few pre-booted containers,
each already running with Jupyter base_url = /nb/<uuid>/ (uuid pre-assigned at
warm time) + its own volume + token. Creating a notebook simply CLAIMS a warm
slot, so the notebook's id == that container's uuid and it is already serving.
Re-opening a *stopped* notebook (after close / broker restart) does an on-demand
start on its saved volume.

Compute is ephemeral; files persist in the per-notebook Docker volume.
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
THEME_PLUGIN = "@jupyterlab/apputils-extension:themes"


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def base_url(uuid: str) -> str:
    return f"/nb/{uuid}/"


class NotebookManager:
    def __init__(self):
        self.client = docker.from_env()
        self.runtime = {}             # uuid -> {container, port, token, volume}
        self.pool = []                # warm slots {uuid, volume, token, port, container}
        self.lock = threading.RLock()
        threading.Thread(target=self._fill_pool, daemon=True).start()

    # ----- volumes -----------------------------------------------------------
    def new_volume(self) -> str:
        name = f"nex-{secrets.token_hex(6)}"
        self.client.volumes.create(name=name, labels=LABEL)
        return name

    def remove_volume(self, volume: str):
        try:
            self.client.volumes.get(volume).remove(force=True)
        except Exception:
            pass

    # ----- container lifecycle ----------------------------------------------
    def _start(self, uuid, volume, token, port):
        return self.client.containers.run(
            IMAGE, detach=True,
            command=["start-notebook.py", f"--ServerApp.base_url={base_url(uuid)}"],
            environment={"JUPYTER_TOKEN": token},
            ports={f"{NB_PORT}/tcp": port},
            volumes={volume: {"bind": "/home/jovyan/work", "mode": "rw"}},
            labels=LABEL,
        )

    def _wait_ready(self, port, token, uuid, timeout=90):
        url = f"http://localhost:{port}{base_url(uuid)}api?token={token}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.4)
        return False

    # ----- warm pool ---------------------------------------------------------
    def _warm_one(self) -> dict:
        uuid = secrets.token_hex(8)
        volume = self.new_volume()
        token = secrets.token_hex(16)
        port = _free_port()
        c = self._start(uuid, volume, token, port)
        if not self._wait_ready(port, token, uuid):
            try:
                c.remove(force=True)
            except Exception:
                pass
            self.remove_volume(volume)
            raise RuntimeError("warm container did not become ready")
        return {"uuid": uuid, "volume": volume, "token": token, "port": port, "container": c}

    def _fill_pool(self):
        while True:
            with self.lock:
                need = POOL_SIZE - len(self.pool)
            if need <= 0:
                return
            try:
                slot = self._warm_one()
            except Exception:
                return
            with self.lock:
                self.pool.append(slot)

    def claim(self) -> dict:
        """Claim a warm slot (instant when the pool is non-empty).

        Returns {uuid, volume, token}; registers it as running and refills the
        pool in the background.
        """
        with self.lock:
            slot = self.pool.pop(0) if self.pool else None
        if slot is None:                       # pool empty -> warm one now (slower)
            slot = self._warm_one()
        with self.lock:
            self.runtime[slot["uuid"]] = {
                "container": slot["container"], "port": slot["port"],
                "token": slot["token"], "volume": slot["volume"]}
        threading.Thread(target=self._fill_pool, daemon=True).start()
        return {"uuid": slot["uuid"], "volume": slot["volume"], "token": slot["token"]}

    def ensure_running(self, uuid: str, volume: str, theme: str):
        """Start a STOPPED notebook's container on its saved volume (on-demand)."""
        with self.lock:
            if uuid in self.runtime:
                return
        token = secrets.token_hex(16)
        port = _free_port()
        c = self._start(uuid, volume, token, port)
        if not self._wait_ready(port, token, uuid):
            try:
                c.remove(force=True)
            except Exception:
                pass
            raise RuntimeError("notebook container did not become ready")
        self._set_theme(port, token, uuid, theme)
        with self.lock:
            self.runtime[uuid] = {"container": c, "port": port, "token": token, "volume": volume}

    def target(self, uuid: str):
        with self.lock:
            rt = self.runtime.get(uuid)
        return {"port": rt["port"], "token": rt["token"]} if rt else None

    def is_running(self, uuid: str) -> bool:
        with self.lock:
            return uuid in self.runtime

    def stop(self, uuid: str):
        with self.lock:
            rt = self.runtime.pop(uuid, None)
        if rt and rt.get("container") is not None:
            try:
                rt["container"].remove(force=True)
            except Exception:
                pass

    # ----- theme sync --------------------------------------------------------
    def _set_theme(self, port, token, uuid, theme):
        body = json.dumps({"raw": json.dumps({"theme": theme})}).encode()
        url = f"http://localhost:{port}{base_url(uuid)}lab/api/settings/{THEME_PLUGIN}"
        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Authorization", f"token {token}")
        req.add_header("Content-Type", "application/json")
        try:
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    def set_theme(self, uuid: str, theme: str):
        with self.lock:
            rt = self.runtime.get(uuid)
        if rt:
            self._set_theme(rt["port"], rt["token"], uuid, theme)

    def shutdown(self):
        with self.lock:
            items = list(self.runtime.values()) + self.pool
            self.runtime.clear()
            self.pool.clear()
        for it in items:
            if it.get("container") is not None:
                try:
                    it["container"].remove(force=True)
                except Exception:
                    pass
