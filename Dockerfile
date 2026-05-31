# ==========================================================================

#  Build:  docker build -t nexalytica-notebook .
#  Run:    docker run --rm -p 8888:8888 -e JUPYTER_TOKEN=nexalytica nexalytica-notebook
#  Open:   http://localhost:8888/?token=nexalytica
# ==========================================================================
FROM quay.io/jupyter/base-notebook:latest

COPY dist/nexalytica-themes /opt/conda/share/jupyter/labextensions/nexalytica-themes


COPY custom.css /home/jovyan/.jupyter/custom/custom.css


COPY overrides.json /opt/conda/share/jupyter/lab/settings/overrides.json


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
