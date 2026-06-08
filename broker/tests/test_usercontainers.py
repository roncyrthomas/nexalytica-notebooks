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


def test_ensure_running_creates_volume(fake_ops, clock):
    mgr = make_mgr(fake_ops, clock)
    mgr.ensure_running("u1", "key1", "nex-vol-u1")
    fake_ops.create_volume.assert_called_once_with("nex-vol-u1")
