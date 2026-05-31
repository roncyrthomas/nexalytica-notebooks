"""Auth + persistence (SQLite): users, signed sessions, per-user notebooks.

Passwords are pbkdf2-hashed. Sessions are stateless signed cookies
(hmac-SHA256 over "<uid>:<expiry>"), so concurrent browsers = independent
sessions with no server-side session store.
"""
import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DATA_DIR, "app.db")
SECRET_PATH = os.path.join(DATA_DIR, "secret.key")
COOKIE_NAME = "nx_session"
SESSION_TTL = 7 * 24 * 3600
_PBKDF2_ROUNDS = 120_000

os.makedirs(DATA_DIR, exist_ok=True)
_lock = threading.Lock()


def _load_secret() -> bytes:
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "rb") as f:
            return f.read()
    s = secrets.token_bytes(32)
    with open(SECRET_PATH, "wb") as f:
        f.write(s)
    return s


SECRET = _load_secret()


def _db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS users ("
                  "id TEXT PRIMARY KEY, email TEXT UNIQUE, pw TEXT, created REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS notebooks ("
                  "id TEXT PRIMARY KEY, user_id TEXT, name TEXT, theme TEXT, "
                  "volume TEXT, secret TEXT, created REAL)")


# ----- passwords -------------------------------------------------------------
def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return f"{salt}${h}"


def verify_pw(pw: str, stored: str) -> bool:
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return hmac.compare_digest(calc, h)


# ----- users -----------------------------------------------------------------
def create_user(email: str, pw: str) -> str | None:
    uid = secrets.token_hex(8)
    with _lock, _db() as c:
        try:
            c.execute("INSERT INTO users VALUES (?,?,?,?)",
                      (uid, email.lower().strip(), hash_pw(pw), time.time()))
        except sqlite3.IntegrityError:
            return None
    return uid


def authenticate(email: str, pw: str) -> str | None:
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email=?",
                        (email.lower().strip(),)).fetchone()
    return row["id"] if row and verify_pw(pw, row["pw"]) else None


def get_user(uid: str):
    with _db() as c:
        return c.execute("SELECT id, email FROM users WHERE id=?", (uid,)).fetchone()


# ----- sessions (signed cookie) ----------------------------------------------
def make_session(uid: str) -> str:
    payload = f"{uid}:{int(time.time()) + SESSION_TTL}"
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def read_session(cookie: str | None) -> str | None:
    if not cookie:
        return None
    try:
        raw = base64.urlsafe_b64decode(cookie.encode()).decode()
        uid, exp, sig = raw.rsplit(":", 2)
    except Exception:
        return None
    payload = f"{uid}:{exp}"
    good = hmac.compare_digest(
        hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest(), sig)
    if good and int(exp) > time.time():
        return uid
    return None


# ----- notebooks (metadata; runtime state lives in manager) ------------------
def create_notebook_row(user_id: str, name: str, theme: str, volume: str) -> dict:
    nid = secrets.token_hex(8)
    sec = secrets.token_urlsafe(16)
    with _lock, _db() as c:
        c.execute("INSERT INTO notebooks VALUES (?,?,?,?,?,?,?)",
                  (nid, user_id, name, theme, volume, sec, time.time()))
    return {"id": nid, "user_id": user_id, "name": name, "theme": theme,
            "volume": volume, "secret": sec}


def list_notebooks(user_id: str) -> list[dict]:
    with _db() as c:
        rows = c.execute("SELECT * FROM notebooks WHERE user_id=? ORDER BY created",
                         (user_id,)).fetchall()
    return [dict(r) for r in rows]


def get_notebook(nid: str) -> dict | None:
    with _db() as c:
        row = c.execute("SELECT * FROM notebooks WHERE id=?", (nid,)).fetchone()
    return dict(row) if row else None


def rename_notebook(nid: str, user_id: str, name: str) -> bool:
    with _lock, _db() as c:
        cur = c.execute("UPDATE notebooks SET name=? WHERE id=? AND user_id=?",
                        (name, nid, user_id))
    return cur.rowcount > 0


def delete_notebook_row(nid: str, user_id: str) -> bool:
    with _lock, _db() as c:
        cur = c.execute("DELETE FROM notebooks WHERE id=? AND user_id=?", (nid, user_id))
    return cur.rowcount > 0
