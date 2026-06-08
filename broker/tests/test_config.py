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
