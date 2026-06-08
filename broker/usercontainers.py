"""Per-user container manager: one container per user, on-demand.

Compute is ephemeral; only the user's named volume persists. The Docker layer
and the clock are injected so all logic here is unit-testable without Docker.
"""
import logging
import secrets
import threading
import time

import config
from docker_ops import DockerOps, free_port

log = logging.getLogger(__name__)


class UserContainerManager:
    def __init__(self, ops=None, now=time.time):
        self.ops = ops or DockerOps()
        self._now = now
        self.runtime = {}            # user_id -> {container, port, token, last_active}
        self.lock = threading.RLock()
        self._user_locks = {}        # user_id -> Lock (serialize same-user starts)
        self.ops.ensure_network()

    def _user_lock(self, user_id):
        with self.lock:
            lk = self._user_locks.get(user_id)
            if lk is None:
                lk = threading.Lock()
                self._user_locks[user_id] = lk
            return lk

    def ensure_running(self, user_id: str, container_key: str, volume: str) -> dict:
        """Reuse the user's running container, or start one on their volume.
        Returns {port, token}. Raises RuntimeError if the container never
        becomes ready."""
        with self.lock:
            rt = self.runtime.get(user_id)
            if rt:
                rt["last_active"] = self._now()
                return {"port": rt["port"], "token": rt["token"]}

        with self._user_lock(user_id):
            # re-check: another thread may have started it while we waited
            with self.lock:
                rt = self.runtime.get(user_id)
                if rt:
                    rt["last_active"] = self._now()
                    return {"port": rt["port"], "token": rt["token"]}

            token = secrets.token_hex(16)
            port = free_port()
            container = self.ops.run_container(
                user_id=user_id, container_key=container_key,
                token=token, volume=volume, port=port)
            if not self.ops.wait_ready(port, container_key, token):
                self.ops.remove_container(container)
                raise RuntimeError("user container did not become ready")
            with self.lock:
                self.runtime[user_id] = {
                    "container": container, "port": port, "token": token,
                    "last_active": self._now()}
            return {"port": port, "token": token}

    def touch(self, user_id: str):
        with self.lock:
            rt = self.runtime.get(user_id)
            if rt:
                rt["last_active"] = self._now()

    def target(self, user_id: str):
        with self.lock:
            rt = self.runtime.get(user_id)
        return {"port": rt["port"], "token": rt["token"]} if rt else None

    def is_running(self, user_id: str) -> bool:
        with self.lock:
            return user_id in self.runtime

    def stop(self, user_id: str):
        with self.lock:
            rt = self.runtime.pop(user_id, None)
            self._user_locks.pop(user_id, None)   # avoid unbounded growth
        if rt:
            self.ops.remove_container(rt["container"])

    def idle_user_ids(self) -> list:
        cutoff = self._now() - config.IDLE_TIMEOUT
        with self.lock:
            return [uid for uid, rt in self.runtime.items()
                    if rt["last_active"] < cutoff]

    def reap_idle(self):
        for uid in self.idle_user_ids():
            self.stop(uid)

    def reap_orphans(self):
        with self.lock:
            known_ids = {rt["container"].id for rt in self.runtime.values()}
        for container in self.ops.list_broker_containers():
            if container.id not in known_ids:
                self.ops.remove_container(container)

    def reap_once(self):
        self.reap_idle()
        self.reap_orphans()

    def start_reaper(self):
        if getattr(self, "_reaper_thread", None) and self._reaper_thread.is_alive():
            return                              # idempotent: don't leak threads
        self._stop_evt = threading.Event()
        self._reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
        self._reaper_thread.start()

    def _reaper_loop(self):
        while not self._stop_evt.wait(config.REAP_INTERVAL):
            try:
                self.reap_once()
            except Exception:
                log.exception("reaper pass failed")   # keep looping, but surface it

    def shutdown(self):
        if getattr(self, "_stop_evt", None) is not None:
            self._stop_evt.set()
        with self.lock:
            items = list(self.runtime.values())
            self.runtime.clear()
            self._user_locks.clear()
        for rt in items:
            self.ops.remove_container(rt["container"])
