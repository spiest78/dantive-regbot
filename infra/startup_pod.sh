#!/usr/bin/env bash
set -euo pipefail

# 0) Bypass guard for troubleshooting (leave this in!)
if [ -f /workspace/.disable_startup ] || [ -n "${SKIP_STARTUP:-}" ]; then
  echo "[startup_pod] bypassed"; exit 0
fi

# 1) Ensure NV structure
mkdir -p /workspace/{logs,postgres,qdrant,ollama,datasets,markers,bin}

# 2) Sync repo (assumes repo already cloned at /workspace/dantive-regbot)
cd /workspace/dantive-regbot
# Be conservative: reset local changes, clean untracked files (safe on diagnostic branch)
git reset --hard
git clean -fd
git fetch --all --prune

# Use diagnostic branch when testing; fall back to main if not present
BRANCH="${STARTUP_BRANCH:-runpod-diagnose-20250924}"
git checkout "${BRANCH}" || git checkout main
git pull --rebase

# 3) Patch public API URL if Runpod sets API_PROXY_HOST
if [ -n "${API_PROXY_HOST:-}" ] && [ -f infra/.env ]; then
  # replace API_PUBLIC_BASE line if present; otherwise append
  if grep -q '^API_PUBLIC_BASE=' infra/.env 2>/dev/null; then
    sed -i "s#^API_PUBLIC_BASE=.*#API_PUBLIC_BASE=https://${API_PROXY_HOST}#g" infra/.env
  else
    echo "API_PUBLIC_BASE=https://${API_PROXY_HOST}" >> infra/.env
  fi
fi

# 4) Launch supervisor with the repo's config (supervisor file must be in repo)
SUPERVISOR_CONF="/workspace/dantive-regbot/infra/supervisor/supervisord.conf"
if [ ! -f "${SUPERVISOR_CONF}" ]; then
  echo "[startup_pod] missing supervisord.conf at ${SUPERVISOR_CONF}" >&2
  exit 1
fi

# Start supervisord (it will handle starting services). Use -c to point to the repo copy.
# --- bootstrap dependencies and venv ---

bash /workspace/dantive-regbot/infra/bootstrap_deps.sh || exit 1

[ -d /workspace/venv ] || python3 -m venv /workspace/venv

/workspace/venv/bin/pip install --upgrade pip

[ -f /workspace/dantive-regbot/services/api/requirements.txt ] && /workspace/venv/bin/pip install -r /workspace/dantive-regbot/services/api/requirements.txt || true

[ -f /workspace/dantive-regbot/services/ui/requirements.txt ]  && /workspace/venv/bin/pip install -r /workspace/dantive-regbot/services/ui/requirements.txt  || true

exec supervisord -c "${SUPERVISOR_CONF}"
