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
