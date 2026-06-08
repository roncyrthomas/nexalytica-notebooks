import os
import tempfile

import auth


def _fresh_db(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(auth, "DB_PATH", os.path.join(str(tmp_path), "app.db"))
    auth.init_db()


def test_create_user_assigns_container_key_and_volume(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    uid = auth.create_user("a@b.com", "secret1")
    u = auth.get_user_full(uid)
    assert u["container_key"] and len(u["container_key"]) >= 16
    assert u["volume"] == f"nex-vol-{uid}"


def test_notebook_row_has_path_not_volume(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    uid = auth.create_user("a@b.com", "secret1")
    nb = auth.create_notebook_row(uid, "My NB", "Nexalytica Default Dark")
    assert nb["path"] == f"{nb['id']}.ipynb"
    assert "volume" not in nb and "secret" not in nb
    got = auth.get_notebook(nb["id"])
    assert got["path"] == nb["path"] and got["user_id"] == uid
