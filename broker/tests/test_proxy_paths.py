import proxy


def test_build_target_url_joins_and_keeps_query():
    url = proxy.build_target_url(40000, "u/key1/api/contents/x.ipynb", "a=1&b=2")
    assert url == "http://127.0.0.1:40000/u/key1/api/contents/x.ipynb?a=1&b=2"


def test_build_target_url_no_query():
    url = proxy.build_target_url(40000, "u/key1/api/kernels", "")
    assert url == "http://127.0.0.1:40000/u/key1/api/kernels"


def test_build_ws_url_uses_ws_scheme():
    url = proxy.build_ws_url(40000, "u/key1/api/kernels/abc/channels", "session_id=z")
    assert url == "ws://127.0.0.1:40000/u/key1/api/kernels/abc/channels?session_id=z"
