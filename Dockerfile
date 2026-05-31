# ==========================================================================
#  NEXALYTICA NOTEBOOK — skinned Notebook 7 image
#  --------------------------------------------------------------------------
#  - scipy-notebook base: Python + pandas/numpy/matplotlib already installed
#    so the kernel imports fast (the "warm" part of hot start).
#  - Nexalytica brand themes: a prebuilt JupyterLab theme extension registers
#    all 8 brand palettes (Default / Violet / Sky / Monochrome x light+dark),
#    switchable in Settings -> Theme. Prebuilt = no Node needed in this image.
#  - Opens STRAIGHT INTO a single notebook (no file browser, no Lab IDE),
#    via the server's default_url.
#
#  Build:  docker build -t nexalytica-notebook .
#  Run:    docker run --rm -p 8888:8888 -e JUPYTER_TOKEN=nexalytica nexalytica-notebook
#  Open:   http://localhost:8888/?token=nexalytica
# ==========================================================================
FROM quay.io/jupyter/scipy-notebook:latest

# --- Brand theme extension (8 switchable Nexalytica palettes) -------------
#  Prebuilt federated extension (built once with Node in a dev container,
#  baked here as static assets). Themes serve under /lab/api/themes/.
COPY dist/nexalytica-themes /opt/conda/share/jupyter/labextensions/nexalytica-themes

# --- Clean, Apple-like surface (chrome hiding + layout, theme-independent) -
#  Auto-loaded by Notebook 7. Pairs with the slim toolbar in overrides.json.
COPY custom.css /home/jovyan/.jupyter/custom/custom.css

# --- Default to "Nexalytica Default Dark" on first load -------------------
#  Without this the app boots JupyterLab Light (near-white). Verified via
#  the /lab/api/settings themes endpoint.
COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json

# --- Starter notebook TEMPLATE (outside the mount) + seed-on-first-run -----
#  The broker bind-mounts a per-session folder onto ~/work, which hides any
#  file baked into that path. So we keep the template at /opt/nex and a
#  startup hook copies it into ~/work only when missing — the file then
#  persists in the user's folder across sessions.
COPY Welcome.ipynb /opt/nex/Welcome.ipynb
COPY --chmod=755 seed-work.sh /usr/local/bin/before-notebook.d/10-seed-work.sh

# --- Run the Notebook 7 frontend, NOT the JupyterLab IDE ------------------
ENV DOCKER_STACKS_JUPYTER_CMD=notebook

# --- Land directly inside the notebook: no /tree, no launcher, no /lab ----
#  /notebooks/<path> is Notebook 7's single-document view. Must be set on
#  JupyterNotebookApp — Notebook 7 IGNORES c.ServerApp.default_url and forces
#  /tree, so the ServerApp trait silently does nothing (verified empirically).
# Also relax the CSP frame-ancestors so the broker (a different localhost
# origin) can embed the notebook in an iframe. Jupyter defaults to
# `frame-ancestors 'self'`, which blocks cross-port embedding.
RUN cat >> /home/jovyan/.jupyter/jupyter_server_config.py <<'PY'
c.JupyterNotebookApp.default_url = '/notebooks/work/Welcome.ipynb'
c.ServerApp.tornado_settings = {'headers': {'Content-Security-Policy': "frame-ancestors 'self' http://localhost:* http://127.0.0.1:*"}}
PY
