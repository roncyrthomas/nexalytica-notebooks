"""Per-notebook Docker runtime for the multi-user / no-iframe variation.

Each notebook runs its own container with Jupyter base_url = /nb/<uuid>/ so the
broker can reverse-proxy it under that clean path (HTTP + kernel WebSocket).
Compute is ephemeral (container created on open, removed on close); files
persist in the per-notebook Docker volume.
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
        self.lock = threading.RLock()

    # ----- volumes -----------------------------------------------------------
    def new_volume(self) -> str:
        name = f"nex-{secrets.token_hex(6)}"
        self.client.volumes.create(name=name, labels=LABEL)
        return name

    # ----- container lifecycle ----------------------------------------------
    def _wait_ready(self, port, token, uuid, timeout=60):
        url = f"http://localhost:{port}{base_url(uuid)}api?token={token}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    def ensure_running(self, uuid: str, volume: str, theme: str) -> dict:
        """Start the notebook's container if needed; return {port, token}."""
        with self.lock:
            rt = self.runtime.get(uuid)
            if rt is not None:
                return {"port": rt["port"], "token": rt["token"]}
        token = secrets.token_hex(16)
        container = self.client.containers.run(
            IMAGE, detach=True,
            # base_url so the broker can reverse-proxy under /nb/<uuid>/;
            # allow_origin + disable_check_xsrf so cross-origin POSTs from the
            # proxied browser (Origin = broker host) are accepted. The broker is
            # the sole client and already enforces auth + per-user ownership.
            command=["start-notebook.py",
                     f"--ServerApp.base_url={base_url(uuid)}",
                     "--ServerApp.allow_origin=*",
                     "--ServerApp.disable_check_xsrf=True"],
            environment={"JUPYTER_TOKEN": token},
            ports={f"{NB_PORT}/tcp": None},   # Docker picks a free host port (no race)
            volumes={volume: {"bind": "/home/jovyan/work", "mode": "rw"}},
            labels=LABEL,
        )
        container.reload()
        binding = (container.ports or {}).get(f"{NB_PORT}/tcp")
        if not binding:
            try:
                container.remove(force=True)
            except Exception:
                pass
            raise RuntimeError("no host port assigned")
        port = int(binding[0]["HostPort"])
        if not self._wait_ready(port, token, uuid):
            try:
                container.remove(force=True)
            except Exception:
                pass
            raise RuntimeError("notebook container did not become ready")
        self._set_theme(port, token, uuid, theme)
        with self.lock:
            self.runtime[uuid] = {"container": container, "port": port,
                                  "token": token, "volume": volume}
        return {"port": port, "token": token}

    def target(self, uuid: str):
        """Return {port, token} if the notebook is running, else None."""
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

    def remove_volume(self, volume: str):
        try:
            self.client.volumes.get(volume).remove(force=True)
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
            items = list(self.runtime.values())
            self.runtime.clear()
        for rt in items:
            if rt.get("container") is not None:
                try:
                    rt["container"].remove(force=True)
                except Exception:
                    pass
