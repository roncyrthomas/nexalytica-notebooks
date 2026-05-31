#!/bin/bash
# Seed the starter notebook into the work dir on first run.
#
# The broker bind-mounts a per-session host folder onto ${HOME}/work, which
# hides anything baked into that path at build time. This hook runs at
# container startup (after the mount is in place), so it copies the template
# in only when the folder is empty of it — i.e. the very first session for
# that folder. On later sessions the user's own file is already there and is
# left untouched.
set -e
if [ ! -f "${HOME}/work/Welcome.ipynb" ]; then
  cp /opt/nex/Welcome.ipynb "${HOME}/work/Welcome.ipynb"
fi
