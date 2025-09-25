#!/usr/bin/env bash
set -euo pipefail

LOG_DIR=/workspace/logs
REPO_DIR=/workspace/dantive-regbot
SUPERVISOR_CONF="${REPO_DIR}/infra/supervisor/supervisord.conf"

mkdir -p "$LOG_DIR" /workspace/{datasets,markers}

# --- guard to bypass startup ---
if [ -f /workspace/.disable_startup ] || [ -n "${SKIP_STARTUP:-}" ]; then
  echo "[startup_pod] bypassed"
  exit 0
fi

echo "[startup_pod] starting…"

# --- make git trust this worktree ---
git config --global --add safe.directory "$REPO_DIR" || true

# --- ensure we can fetch (SSH → HTTPS fallback) ---
cd "$REPO_DIR"
if ! git fetch --all --prune 2>"$LOG_DIR/git_fetch.err"; then
  if grep -q "Host key verification failed" "$LOG_DIR/git_fetch.err"; then
    echo "[startup_pod] SSH host key failed; switching origin to HTTPS"
    git remote set-url origin "https://github.com/spiest78/dantive-regbot.git"
    git fetch --all --prune
  else
    echo "[startup_pod] fetch failed; see $LOG_DIR/git_fetch.err"
    cat "$LOG_DIR/git_fetch.err" >&2
    exit 1
  fi
fi

# --- checkout branch (diagnostics if present; else main) ---
if git rev-parse --verify origin/runpod-diagnose-20250924 >/dev/null 2>&1; then
  git checkout -f runpod-diagnose-20250924
  git reset --hard origin/runpod-diagnose-20250924
else
  git checkout -f main
  git reset --hard origin/main
fi

# --- ensure supervisord is available ---
if ! command -v supervisord >/dev/null 2>&1; then
  echo "[startup_pod] installing supervisor…"
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y && apt-get install -y supervisor
  else
    python3 -m pip install --upgrade pip
    python3 -m pip install supervisor
  fi
fi

# --- bootstrap dependencies & NV dirs (also installs Ollama if missing) ---
bash "${REPO_DIR}/infra/bootstrap_deps.sh"

# --- ensure app venv and requirements ---
[ -d /workspace/venv ] || python3 -m venv /workspace/venv
/workspace/venv/bin/pip install --upgrade pip

for req in \
  "${REPO_DIR}/services/api/requirements.txt" \
  "${REPO_DIR}/services/ui/requirements.txt"  \
  "${REPO_DIR}/apps/api/requirements.txt"     \
  "${REPO_DIR}/apps/ui/requirements.txt"
do
  [ -f "$req" ] && /workspace/venv/bin/pip install -r "$req" || true
done

# --- Ollama preflight (repo-first, before supervisord) ---
export OLLAMA_MODELS=/workspace/ollama
mkdir -p "$OLLAMA_MODELS"

# ensure ollama binary exists (bootstrap_deps should have installed it)
if ! [ -x /usr/local/bin/ollama ]; then
  echo "[startup_pod] ollama missing, re-running bootstrap…"
  bash "${REPO_DIR}/infra/bootstrap_deps.sh"
fi

# verify ollama actually works
if ! /usr/local/bin/ollama --version >/dev/null 2>&1; then
  echo "[startup_pod] ERROR: ollama not available after bootstrap"
  exit 1
fi

# free 11434 if a stray 'ollama serve' is still running
if ss -ltn | awk '{print $4}' | grep -qE '(^|:)11434$'; then
  echo "[startup_pod] freeing port 11434 (killing stray ollama)…"
  pkill -9 -f '/usr/local/bin/ollama serve' || true
fi

# --- deploy helper scripts for supervisor ---
mkdir -p /workspace/bin
install -Dm755 "${REPO_DIR}/ops/pull_models.sh" /workspace/bin/ollama_pull.sh

echo "[startup_pod] launching supervisord…"
exec "$(command -v supervisord)" -c "${SUPERVISOR_CONF}"
