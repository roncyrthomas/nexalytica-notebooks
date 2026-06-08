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
