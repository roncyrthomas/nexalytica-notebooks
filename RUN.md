# Nexalytica Notebooks — Run & Test

A multi-user notebook platform: a FastAPI **broker** that gives each user their own
isolated Docker container running Jupyter, fronted by a custom (no-JupyterLab) web UI.

- **One container per user** (not per notebook): on-demand start, reused across the
  user's notebooks, auto-stopped after 1 h idle, capped at 0.5 CPU / 1 GB.
- **Security:** containers hold only their own Jupyter token (no DB creds / platform
  secrets), bind to `127.0.0.1` only, can reach the internet but not each other or the host DB.
- **Custom UI:** your own editor (cells, run, outputs, save, export) talking to the
  container's Jupyter REST + kernel WebSocket through the authenticated broker.

Full design lives in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

---

## Prerequisites
- **Docker** running (Docker Desktop on Windows/macOS, or the daemon on Linux). The broker
  talks to the Docker socket to manage containers.
- **Python 3.11+**.

## 1. Build the per-user notebook image (one time)
From the repo root:
```bash
docker build -t nexalytica-notebook .
```

## 2. Install the broker's Python deps
```bash
cd broker
pip install -r requirements.txt
```

## 3. (Optional) start clean
Wipes the local DB and any old broker-labelled containers/volumes:
```bash
# from broker/, Docker must be running
python reset.py --yes
```

## 4. Run the broker
```bash
# from broker/
python run.py
```
Serves on **http://127.0.0.1:8000**. (Use `python run.py` — it selects the `wsproto`
WebSocket impl the kernel connection needs. To expose on your LAN: set `HOST=0.0.0.0`.)

## 5. Use it
1. Open **http://127.0.0.1:8000** → **Register** an account.
2. **+ New notebook** → the editor opens; the kernel auto-starts (pill: starting → idle).
3. Type `print(2+2)`, press **Shift+Enter** → see `4`. Try a pandas DataFrame (HTML table),
   a matplotlib plot (PNG), and something that raises (red traceback).
4. **Ctrl+S** / Save persists it; reload to confirm. Rename via the title or the sidebar.
   Switch themes (8 palettes). Export `.ipynb` / `.py` / `.html`.

First open of a notebook has a ~3–4 s cold start while the container boots; after that it's
instant and the kernel stays warm (reopen within 5 min reconnects to the same kernel).

---

## Tests
From `broker/`:
```bash
python -m pytest -q                 # unit tests (mocked Docker) — ~28 tests
python -m pytest -m integration -q  # real-Docker security gate (needs Docker + the image)
```
The integration gate asserts the hard security properties on a real container: secret-free
environment and loopback-only port binding.

## Notes
- `broker/data/` (SQLite DB + signing key) is gitignored and created at runtime.
- Static assets are served `no-cache` so redeploys never serve stale JS to the browser.
