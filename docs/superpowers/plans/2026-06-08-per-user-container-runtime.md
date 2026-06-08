# Per-User Container Runtime — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, self-contained `UserContainerManager` that provisions **one Docker container per user** on demand, enforces resource/network/secret isolation, and reaps idle + orphaned containers.

**Architecture:** Three new broker modules built *alongside* the running app (no edits to `app.py`/`proxy.py`/`auth.py` in this plan): `config.py` (constants), `docker_ops.py` (thin, mockable Docker SDK wrapper), `usercontainers.py` (`UserContainerManager` — runtime table, lifecycle, reapers). The clock and the Docker layer are dependency-injected so logic is unit-testable without Docker; one marked integration test exercises a real container. Cutover to this manager happens in Plan 2.

**Tech Stack:** Python 3.11, `docker` SDK 7.1, pytest, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-06-08-per-user-container-platform-design.md` (§4 Runtime, §4.6 security).

---

## File Structure

- Create: `broker/config.py` — all runtime constants (image, limits, idle timeout, network, labels, base_url helper).
- Create: `broker/docker_ops.py` — `DockerOps`: network/volume/container ops + readiness probe. The only module that imports `docker`.
- Create: `broker/usercontainers.py` — `UserContainerManager`: per-user runtime table, `ensure_running`/`touch`/`target`/`stop`, idle + orphan reapers, background loop.
- Create: `broker/tests/__init__.py`, `broker/tests/conftest.py` — test fixtures (fake clock, fake DockerOps).
- Create: `broker/tests/test_config.py`, `broker/tests/test_docker_ops.py`, `broker/tests/test_usercontainers.py`, `broker/tests/test_integration_runtime.py`.
- Modify: `broker/requirements.txt` — add `pytest`, `pytest-mock`.

No other files change in this plan.

---

## Task 1: Test scaffolding + dependencies

**Files:**
- Modify: `broker/requirements.txt`
- Create: `broker/tests/__init__.py`
- Create: `broker/pytest.ini`

- [ ] **Step 1: Add test deps to `broker/requirements.txt`** (append these two lines)

```
pytest==8.3.4
pytest-mock==3.14.0
```

- [ ] **Step 2: Install**

Run: `cd broker && pip install -r requirements.txt`
Expected: pytest and pytest-mock install successfully.

- [ ] **Step 3: Create `broker/tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `broker/pytest.ini`**

```ini
[pytest]
markers =
    integration: tests that start real Docker containers (deselect with -m "not integration")
addopts = -m "not integration"
testpaths = tests
```

- [ ] **Step 5: Verify pytest discovers nothing yet (no failures)**

Run: `cd broker && python -m pytest -q`
Expected: `no tests ran` (exit code 5) — scaffolding works.

- [ ] **Step 6: Commit**

```bash
git add broker/requirements.txt broker/tests/__init__.py broker/pytest.ini
git commit -m "test(runtime): add pytest scaffolding for broker"
```

---

## Task 2: `config.py` constants

**Files:**
- Create: `broker/config.py`
- Test: `broker/tests/test_config.py`

- [ ] **Step 1: Write the failing test** — `broker/tests/test_config.py`

```python
import config


def test_resource_limits_are_sane():
    assert config.NANO_CPUS == 500_000_000          # 0.5 CPU
    assert config.MEM_LIMIT == "1g"
    assert config.PIDS_LIMIT == 256


def test_idle_and_reap_defaults():
    assert config.IDLE_TIMEOUT == 3600              # 1 hour
    assert config.REAP_INTERVAL == 60


def test_labels_and_network():
    assert config.LABEL == {config.LABEL_KEY: "1"}
    assert config.LABEL_KEY == "nexalytica.broker"
    assert config.USER_LABEL_KEY == "nexalytica.user"
    assert config.NETWORK_NAME == "nexalytica-net"


def test_base_url_format():
    assert config.base_url("abc123") == "/u/abc123/"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd broker && python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Create `broker/config.py`**

```python
"""Runtime constants for the per-user container platform.

All values are overridable via environment variables so deployment can tune
resource tiers and timeouts without code changes.
"""
import os

# image + jupyter
IMAGE = os.environ.get("NEX_IMAGE", "nexalytica-notebook")
NB_PORT = 8888
WORK_DIR = "/home/jovyan/work"

# labels (used for orphan reaping + identifying our containers)
LABEL_KEY = "nexalytica.broker"
USER_LABEL_KEY = "nexalytica.user"
LABEL = {LABEL_KEY: "1"}

# network: a dedicated bridge with inter-container comms DISABLED
NETWORK_NAME = os.environ.get("NEX_NETWORK", "nexalytica-net")

# lifecycle
IDLE_TIMEOUT = int(os.environ.get("NEX_IDLE_TIMEOUT", "3600"))   # seconds
REAP_INTERVAL = int(os.environ.get("NEX_REAP_INTERVAL", "60"))   # seconds

# resource caps (per container == per user)
NANO_CPUS = int(os.environ.get("NEX_NANO_CPUS", str(500_000_000)))  # 0.5 CPU
MEM_LIMIT = os.environ.get("NEX_MEM_LIMIT", "1g")
PIDS_LIMIT = int(os.environ.get("NEX_PIDS_LIMIT", "256"))


def base_url(container_key: str) -> str:
    """Per-user Jupyter base_url. One Lab/server per user, keyed by an
    unguessable random container_key (not the user id)."""
    return f"/u/{container_key}/"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd broker && python -m pytest tests/test_config.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add broker/config.py tests/test_config.py
git commit -m "feat(runtime): add config constants for per-user containers"
```

---

## Task 3: `docker_ops.py` — Docker SDK wrapper

This isolates every Docker call behind one class so the manager can be unit-tested with a fake. Tests inject a `MagicMock` client and assert the exact kwargs (limits, loopback port bind, secret-free env, network, labels).

**Files:**
- Create: `broker/docker_ops.py`
- Test: `broker/tests/test_docker_ops.py`

- [ ] **Step 1: Write the failing test** — `broker/tests/test_docker_ops.py`

```python
from unittest.mock import MagicMock

import docker.errors

import config
from docker_ops import DockerOps, free_port


def test_free_port_returns_int_in_range():
    p = free_port()
    assert isinstance(p, int) and 1024 < p < 65536


def test_ensure_network_creates_with_icc_disabled_when_missing():
    client = MagicMock()
    client.networks.get.side_effect = docker.errors.NotFound("nope")
    ops = DockerOps(client=client)

    ops.ensure_network()

    client.networks.create.assert_called_once()
    _, kwargs = client.networks.create.call_args
    assert kwargs["driver"] == "bridge"
    assert kwargs["options"]["com.docker.network.bridge.enable_icc"] == "false"


def test_ensure_network_noop_when_present():
    client = MagicMock()
    client.networks.get.return_value = MagicMock()       # found
    ops = DockerOps(client=client)

    ops.ensure_network()

    client.networks.create.assert_not_called()


def test_run_container_enforces_limits_network_and_secret_free_env():
    client = MagicMock()
    ops = DockerOps(client=client)

    ops.run_container(user_id="u1", container_key="key1",
                      token="tok", volume="nex-vol-u1", port=40000)

    _, kwargs = client.containers.run.call_args
    # resource caps
    assert kwargs["nano_cpus"] == config.NANO_CPUS
    assert kwargs["mem_limit"] == config.MEM_LIMIT
    assert kwargs["memswap_limit"] == config.MEM_LIMIT
    assert kwargs["pids_limit"] == config.PIDS_LIMIT
    # ZERO-SECRET: only JUPYTER_TOKEN may be present
    assert kwargs["environment"] == {"JUPYTER_TOKEN": "tok"}
    # port published to loopback only
    assert kwargs["ports"] == {f"{config.NB_PORT}/tcp": ("127.0.0.1", 40000)}
    # isolated network + ownership labels
    assert kwargs["network"] == config.NETWORK_NAME
    assert kwargs["labels"][config.LABEL_KEY] == "1"
    assert kwargs["labels"][config.USER_LABEL_KEY] == "u1"
    # terminals disabled + scoped root in the command
    cmd = " ".join(kwargs["command"])
    assert "terminals_enabled=False" in cmd
    assert f"base_url={config.base_url('key1')}" in cmd


def test_list_broker_containers_filters_by_label():
    client = MagicMock()
    ops = DockerOps(client=client)

    ops.list_broker_containers()

    _, kwargs = client.containers.list.call_args
    assert kwargs["all"] is True
    assert kwargs["filters"] == {"label": f"{config.LABEL_KEY}=1"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd broker && python -m pytest tests/test_docker_ops.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'docker_ops'`.

- [ ] **Step 3: Create `broker/docker_ops.py`**

```python
"""Thin, mockable wrapper around the Docker SDK.

The ONLY module that imports `docker`. Everything the manager needs goes
through here so the manager can be unit-tested against a fake client.
"""
import socket
import time
import urllib.request

import docker
import docker.errors

import config


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DockerOps:
    def __init__(self, client=None):
        self.client = client or docker.from_env()

    # ----- network -----------------------------------------------------------
    def ensure_network(self):
        """Create the dedicated bridge with inter-container comms disabled,
        if it does not already exist."""
        try:
            self.client.networks.get(config.NETWORK_NAME)
        except docker.errors.NotFound:
            self.client.networks.create(
                config.NETWORK_NAME,
                driver="bridge",
                options={"com.docker.network.bridge.enable_icc": "false"},
                labels=config.LABEL,
            )

    # ----- volumes -----------------------------------------------------------
    def create_volume(self, name: str):
        try:
            return self.client.volumes.get(name)
        except docker.errors.NotFound:
            return self.client.volumes.create(name=name, labels=config.LABEL)

    def remove_volume(self, name: str):
        try:
            self.client.volumes.get(name).remove(force=True)
        except Exception:
            pass

    # ----- containers --------------------------------------------------------
    def run_container(self, *, user_id, container_key, token, volume, port):
        return self.client.containers.run(
            config.IMAGE, detach=True,
            name=f"nex-u-{user_id}",
            command=[
                "start-notebook.py",
                f"--ServerApp.base_url={config.base_url(container_key)}",
                f"--ServerApp.root_dir={config.WORK_DIR}",
                "--ServerApp.terminals_enabled=False",
                # broker is the only origin that reaches the container; it
                # authenticates with the injected token, so relax browser checks.
                "--ServerApp.disable_check_xsrf=True",
                "--ServerApp.allow_origin=*",
            ],
            # ZERO-SECRET: nothing but the container's own single-tenant token.
            environment={"JUPYTER_TOKEN": token},
            ports={f"{config.NB_PORT}/tcp": ("127.0.0.1", port)},
            volumes={volume: {"bind": config.WORK_DIR, "mode": "rw"}},
            network=config.NETWORK_NAME,
            nano_cpus=config.NANO_CPUS,
            mem_limit=config.MEM_LIMIT,
            memswap_limit=config.MEM_LIMIT,
            pids_limit=config.PIDS_LIMIT,
            labels={**config.LABEL, config.USER_LABEL_KEY: user_id},
        )

    def remove_container(self, container):
        try:
            container.remove(force=True)
        except Exception:
            pass

    def list_broker_containers(self):
        return self.client.containers.list(
            all=True, filters={"label": f"{config.LABEL_KEY}=1"})

    # ----- readiness ---------------------------------------------------------
    def wait_ready(self, port, container_key, token, timeout=90) -> bool:
        url = (f"http://127.0.0.1:{port}{config.base_url(container_key)}"
               f"api?token={token}")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(0.4)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd broker && python -m pytest tests/test_docker_ops.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add broker/docker_ops.py tests/test_docker_ops.py
git commit -m "feat(runtime): docker_ops wrapper — limits, loopback bind, secret-free env, ICC-off network"
```

---

## Task 4: `UserContainerManager` — provision, reuse, target, stop

**Files:**
- Create: `broker/usercontainers.py`
- Create: `broker/tests/conftest.py`
- Test: `broker/tests/test_usercontainers.py`

- [ ] **Step 1: Create `broker/tests/conftest.py`** (shared fakes)

```python
from unittest.mock import MagicMock

import pytest


class FakeClock:
    """Deterministic, injectable clock for idle-timeout tests."""
    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def fake_ops():
    """A DockerOps double. run_container returns a fresh fake container each
    call; wait_ready succeeds by default."""
    ops = MagicMock()
    ops.wait_ready.return_value = True

    def _run(**kwargs):
        c = MagicMock()
        c.id = f"cid-{kwargs['user_id']}"
        c.user_id = kwargs["user_id"]
        return c

    ops.run_container.side_effect = _run
    return ops
```

- [ ] **Step 2: Write the failing test** — `broker/tests/test_usercontainers.py`

```python
import pytest

from usercontainers import UserContainerManager


def make_mgr(fake_ops, clock):
    return UserContainerManager(ops=fake_ops, now=clock)


def test_first_open_starts_container(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)

    tgt = mgr.ensure_running("u1", "key1", "nex-vol-u1")

    assert fake_ops.run_container.call_count == 1
    assert tgt["port"] > 0 and tgt["token"]
    assert mgr.is_running("u1")


def test_second_open_reuses_same_container(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)

    t1 = mgr.ensure_running("u1", "key1", "nex-vol-u1")
    t2 = mgr.ensure_running("u1", "key1", "nex-vol-u1")

    assert fake_ops.run_container.call_count == 1      # NOT restarted
    assert t1 == t2


def test_failed_readiness_removes_container_and_raises(fake_ops, clock):
    fake_ops.wait_ready.return_value = False
    mgr = make_mgr(fake_ops, clock)

    with pytest.raises(RuntimeError):
        mgr.ensure_running("u1", "key1", "nex-vol-u1")

    fake_ops.remove_container.assert_called_once()
    assert not mgr.is_running("u1")


def test_target_returns_port_and_token(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")

    tgt = mgr.target("u1")

    assert set(tgt) == {"port", "token"}


def test_stop_removes_and_deregisters(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")

    mgr.stop("u1")

    fake_ops.remove_container.assert_called_once()
    assert not mgr.is_running("u1")
    assert mgr.target("u1") is None


def test_touch_updates_last_active(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    clock.advance(50)

    mgr.touch("u1")

    assert mgr.runtime["u1"]["last_active"] == clock()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'usercontainers'`.

- [ ] **Step 4: Create `broker/usercontainers.py`** (lifecycle portion; reapers added in Tasks 5–7)

```python
"""Per-user container manager: one container per user, on-demand.

Compute is ephemeral; only the user's named volume persists. The Docker layer
and the clock are injected so all logic here is unit-testable without Docker.
"""
import secrets
import threading
import time

from docker_ops import DockerOps, free_port


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
        if rt:
            self.ops.remove_container(rt["container"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add broker/usercontainers.py tests/conftest.py tests/test_usercontainers.py
git commit -m "feat(runtime): UserContainerManager — per-user provision/reuse/stop"
```

---

## Task 5: Idle reaper

**Files:**
- Modify: `broker/usercontainers.py` (add `idle_user_ids`, `reap_idle`)
- Test: `broker/tests/test_usercontainers.py` (append)

- [ ] **Step 1: Write the failing test** (append to `broker/tests/test_usercontainers.py`)

```python
import config


def test_idle_user_ids_lists_only_expired(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    clock.advance(config.IDLE_TIMEOUT + 1)
    mgr.ensure_running("u2", "key2", "nex-vol-u2")   # fresh, not idle

    idle = mgr.idle_user_ids()

    assert idle == ["u1"]


def test_reap_idle_stops_expired_only(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    clock.advance(config.IDLE_TIMEOUT + 1)
    mgr.ensure_running("u2", "key2", "nex-vol-u2")

    mgr.reap_idle()

    assert not mgr.is_running("u1")
    assert mgr.is_running("u2")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -k idle -q`
Expected: FAIL — `AttributeError: 'UserContainerManager' object has no attribute 'idle_user_ids'`.

- [ ] **Step 3: Add methods to `broker/usercontainers.py`** (insert after `stop`)

```python
    def idle_user_ids(self) -> list:
        cutoff = self._now() - config.IDLE_TIMEOUT
        with self.lock:
            return [uid for uid, rt in self.runtime.items()
                    if rt["last_active"] < cutoff]

    def reap_idle(self):
        for uid in self.idle_user_ids():
            self.stop(uid)
```

Also add `import config` to the top of `broker/usercontainers.py` (after the existing imports).

- [ ] **Step 4: Run to verify it passes**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add broker/usercontainers.py tests/test_usercontainers.py
git commit -m "feat(runtime): idle reaper (1h default)"
```

---

## Task 6: Orphan reaper

Removes broker-labelled containers that are not in the runtime table (left over from a crash/restart, or old per-notebook containers from before the migration). Volumes are never auto-removed here.

**Files:**
- Modify: `broker/usercontainers.py` (add `reap_orphans`)
- Test: `broker/tests/test_usercontainers.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
from unittest.mock import MagicMock


def test_reap_orphans_removes_unknown_labelled_containers(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    known = mgr.ensure_running("u1", "key1", "nex-vol-u1")  # noqa: F841
    known_container = mgr.runtime["u1"]["container"]

    orphan = MagicMock()
    orphan.id = "cid-orphan"
    fake_ops.list_broker_containers.return_value = [known_container, orphan]

    mgr.reap_orphans()

    # only the orphan is removed; the known container is untouched
    removed = [c.args[0] for c in fake_ops.remove_container.call_args_list]
    assert orphan in removed
    assert known_container not in removed
    assert mgr.is_running("u1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -k orphan -q`
Expected: FAIL — `AttributeError: ... 'reap_orphans'`.

- [ ] **Step 3: Add method to `broker/usercontainers.py`** (insert after `reap_idle`)

```python
    def reap_orphans(self):
        with self.lock:
            known_ids = {rt["container"].id for rt in self.runtime.values()}
        for container in self.ops.list_broker_containers():
            if container.id not in known_ids:
                self.ops.remove_container(container)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add broker/usercontainers.py tests/test_usercontainers.py
git commit -m "feat(runtime): orphan reaper by label"
```

---

## Task 7: Background reaper loop + shutdown

**Files:**
- Modify: `broker/usercontainers.py` (add `reap_once`, `start_reaper`, `shutdown`)
- Test: `broker/tests/test_usercontainers.py` (append)

- [ ] **Step 1: Write the failing test** (append)

```python
def test_reap_once_runs_both_reapers(fake_ops, clock, mocker):
    mgr = make_mgr(fake_ops, clock)
    spy_idle = mocker.spy(mgr, "reap_idle")
    spy_orphan = mocker.spy(mgr, "reap_orphans")
    fake_ops.list_broker_containers.return_value = []

    mgr.reap_once()

    spy_idle.assert_called_once()
    spy_orphan.assert_called_once()


def test_shutdown_stops_all_and_clears(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    mgr.ensure_running("u2", "key2", "nex-vol-u2")

    mgr.shutdown()

    assert fake_ops.remove_container.call_count == 2
    assert mgr.runtime == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd broker && python -m pytest tests/test_usercontainers.py -k "reap_once or shutdown" -q`
Expected: FAIL — missing `reap_once` / `shutdown`.

- [ ] **Step 3: Add methods to `broker/usercontainers.py`** (insert after `reap_orphans`)

```python
    def reap_once(self):
        self.reap_idle()
        self.reap_orphans()

    def start_reaper(self):
        def loop():
            while not self._stop_evt.wait(config.REAP_INTERVAL):
                try:
                    self.reap_once()
                except Exception:
                    pass
        self._stop_evt = threading.Event()
        threading.Thread(target=loop, daemon=True).start()

    def shutdown(self):
        if getattr(self, "_stop_evt", None) is not None:
            self._stop_evt.set()
        with self.lock:
            items = list(self.runtime.values())
            self.runtime.clear()
        for rt in items:
            self.ops.remove_container(rt["container"])
```

- [ ] **Step 4: Run the full unit suite**

Run: `cd broker && python -m pytest -q`
Expected: PASS (all unit tests; 11 passed).

- [ ] **Step 5: Commit**

```bash
git add broker/usercontainers.py tests/test_usercontainers.py
git commit -m "feat(runtime): reaper loop + graceful shutdown"
```

---

## Task 8: Integration test against real Docker (security gate)

Exercises a real container. Marked `integration` so it is skipped by default (`pytest.ini` excludes it); run explicitly. Verifies the spec's §8 security properties: secret-free env, loopback-only port, reuse.

**Files:**
- Test: `broker/tests/test_integration_runtime.py`

- [ ] **Step 1: Write the integration test** — `broker/tests/test_integration_runtime.py`

```python
"""Real-Docker integration tests. Run explicitly:

    cd broker && python -m pytest -m integration -q

Requires a working Docker daemon and the `nexalytica-notebook` image built.
"""
import secrets

import pytest

import docker
import config
from docker_ops import DockerOps, free_port
from usercontainers import UserContainerManager


@pytest.fixture
def docker_available():
    try:
        docker.from_env().ping()
    except Exception:
        pytest.skip("Docker daemon not available")


@pytest.fixture
def ops(docker_available):
    return DockerOps()


@pytest.mark.integration
def test_container_env_is_secret_free(ops):
    """A user with terminal access must find NOTHING but their own token."""
    uid = f"it-{secrets.token_hex(3)}"
    key = secrets.token_hex(8)
    vol = f"nex-vol-{uid}"
    ops.create_volume(vol)
    token = secrets.token_hex(16)
    port = free_port()
    c = ops.run_container(user_id=uid, container_key=key, token=token,
                          volume=vol, port=port)
    try:
        assert ops.wait_ready(port, key, token), "container never became ready"
        # inspect the actual environment the user can read from a terminal/cell
        env = c.attrs["Config"]["Env"]
        secret_like = [e for e in env
                       if any(s in e.upper() for s in
                              ("DB", "PASSWORD", "SECRET", "DATABASE", "AWS", "API_KEY"))]
        assert secret_like == [], f"leaked secret-like env: {secret_like}"
    finally:
        ops.remove_container(c)
        ops.remove_volume(vol)


@pytest.mark.integration
def test_port_published_to_loopback_only(ops):
    uid = f"it-{secrets.token_hex(3)}"
    key = secrets.token_hex(8)
    vol = f"nex-vol-{uid}"
    ops.create_volume(vol)
    port = free_port()
    c = ops.run_container(user_id=uid, container_key=key, token="t",
                          volume=vol, port=port)
    try:
        c.reload()
        binding = c.attrs["NetworkSettings"]["Ports"][f"{config.NB_PORT}/tcp"]
        assert binding[0]["HostIp"] == "127.0.0.1"
    finally:
        ops.remove_container(c)
        ops.remove_volume(vol)


@pytest.mark.integration
def test_manager_reuse_with_real_container(ops):
    uid = f"it-{secrets.token_hex(3)}"
    key = secrets.token_hex(8)
    vol = f"nex-vol-{uid}"
    ops.create_volume(vol)
    mgr = UserContainerManager(ops=ops)
    try:
        t1 = mgr.ensure_running(uid, key, vol)
        t2 = mgr.ensure_running(uid, key, vol)
        assert t1 == t2
    finally:
        mgr.stop(uid)
        ops.remove_volume(vol)
```

- [ ] **Step 2: Run the integration suite** (requires Docker + built image)

Run: `cd broker && python -m pytest -m integration -q`
Expected: PASS (3 passed) — or `skipped` if no Docker daemon.

- [ ] **Step 3: Confirm default run still excludes integration**

Run: `cd broker && python -m pytest -q`
Expected: the 11 unit tests pass; integration tests are deselected.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_runtime.py
git commit -m "test(runtime): real-Docker integration + secret-free/loopback security gate"
```

---

## Plan-vs-Spec Self-Review

- **§4.1 identity/data model** — `container_key`/`volume` flow as args into the manager; the *DB columns* that store them are added in **Plan 2** (cutover), called out here so it isn't mistaken for a gap.
- **§4.2 lifecycle** — Tasks 4 (provision/reuse/touch), 5 (idle reap), 7 (loop). ✓
- **§4.3 no warm pool** — honored (none built). ✓
- **§4.4 resource limits** — Task 3 + assertions. ✓
- **§4.5 network isolation** — Task 3 (`ensure_network` ICC-off, loopback bind). ✓ (Full container-to-container *runtime* probe is environment-dependent; covered by the ICC-off creation assertion + manual verification in Plan 2's deploy checklist.)
- **§4.6 zero-secret** — Task 3 env assertion + Task 8 real-container env scan. ✓
- **Placeholder scan** — none; every step has full code/commands.
- **Type consistency** — `ensure_running(user_id, container_key, volume)`, `target`/`touch`/`stop(user_id)`, `reap_idle`/`reap_orphans`/`reap_once` names match across all tasks. ✓

---

## What Plan 1 deliberately does NOT do (handoff to Plan 2)

- No edits to `app.py`, `proxy.py`, or `auth.py` — the current app keeps running on the old per-notebook path.
- DB schema change (`users.container_key`/`volume`, `notebooks.path`), the `/u/<key>/` proxy routing, the broker contents/kernels API, and the start-clean reset of old containers/volumes are **Plan 2**.
- The custom Core UI is **Plan 3**.
```
