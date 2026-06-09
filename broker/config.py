"""Runtime constants for the per-user container platform.

All values are overridable via environment variables so deployment can tune
resource tiers and timeouts without code changes.
"""
import os

# image + jupyter
IMAGE = os.environ.get("NEX_IMAGE", "nexalytica-notebook")
NB_PORT = 8888
WORK_DIR = "/home/jovyan/work"

# labels (used for orphan reaping + identifying our containers)
LABEL_KEY = "nexalytica.broker"
USER_LABEL_KEY = "nexalytica.user"
LABEL = {LABEL_KEY: "1"}

# network: a dedicated bridge with inter-container comms DISABLED
NETWORK_NAME = os.environ.get("NEX_NETWORK", "nexalytica-net")

# lifecycle
IDLE_TIMEOUT = int(os.environ.get("NEX_IDLE_TIMEOUT", "3600"))   # seconds
REAP_INTERVAL = int(os.environ.get("NEX_REAP_INTERVAL", "60"))   # seconds

# resource caps (per container == per user)
NANO_CPUS = int(os.environ.get("NEX_NANO_CPUS", str(500_000_000)))  # 0.5 CPU
MEM_LIMIT = os.environ.get("NEX_MEM_LIMIT", "1g")
PIDS_LIMIT = int(os.environ.get("NEX_PIDS_LIMIT", "256"))

# kernel culling inside the container: free a kernel after 5 min idle so a
# closed/abandoned notebook stops consuming RAM, while reopening within the
# window reconnects to the still-live kernel (warm).
CULL_IDLE = int(os.environ.get("NEX_CULL_IDLE", "300"))      # seconds
CULL_INTERVAL = int(os.environ.get("NEX_CULL_INTERVAL", "60"))


def base_url(container_key: str) -> str:
    """Per-user Jupyter base_url. One Lab/server per user, keyed by an
    unguessable random container_key (not the user id)."""
    return f"/u/{container_key}/"
