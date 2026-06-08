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
