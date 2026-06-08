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
