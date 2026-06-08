"""Start-clean reset for the per-user migration. DESTRUCTIVE.

Removes the SQLite DB and every broker-labelled container AND volume (old
per-notebook artifacts included). Users must re-register; notebooks start empty.

    cd broker && python reset.py --yes
"""
import os
import sys

import docker

import auth
import config


def reset(confirm: bool):
    if not confirm:
        print("Refusing to reset without --yes")
        return 1
    # 1) DB
    try:
        os.remove(auth.DB_PATH)
        print(f"removed {auth.DB_PATH}")
    except FileNotFoundError:
        pass
    # 2) containers + volumes by label
    client = docker.from_env()
    for c in client.containers.list(all=True,
                                    filters={"label": f"{config.LABEL_KEY}=1"}):
        try:
            c.remove(force=True)
            print(f"removed container {c.name}")
        except Exception as e:
            print(f"container {c.name}: {e}")
    for v in client.volumes.list(filters={"label": f"{config.LABEL_KEY}=1"}):
        try:
            v.remove(force=True)
            print(f"removed volume {v.name}")
        except Exception as e:
            print(f"volume {v.name}: {e}")
    print("reset complete")
    return 0


if __name__ == "__main__":
    sys.exit(reset("--yes" in sys.argv))
