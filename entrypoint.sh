#!/bin/sh
# IMGAgent container entry point: checks the settings, then starts the webhook server.
set -eu

# The private key: a mounted file (compose secret) is preferred over the one-line variable.
if [ -z "${IMGAGENT_PRIVATE_KEY_FILE:-}" ] && [ -f /run/secrets/imgagent_private_key ]; then
  export IMGAGENT_PRIVATE_KEY_FILE=/run/secrets/imgagent_private_key
fi
if [ -n "${IMGAGENT_PRIVATE_KEY_FILE:-}" ] && [ ! -r "$IMGAGENT_PRIVATE_KEY_FILE" ]; then
  echo "IMGAgent: can't read the private key at $IMGAGENT_PRIVATE_KEY_FILE" >&2
  exit 1
fi

# The root file system is read-only: git's global config goes to the /tmp tmpfs. The git identity is set per
# commit by the jobs; this only keeps git quiet.
export HOME=/tmp/home
mkdir -p "$HOME"
git config --global init.defaultBranch main
git config --global advice.detachedHead false

exec python -m imgagent.server "$@"
