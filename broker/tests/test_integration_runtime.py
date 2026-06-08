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
