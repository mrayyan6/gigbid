#!/usr/bin/env bash
# Starts every GigBid service in one container and supervises them.
# Ports (all on 127.0.0.1 except the web port): GigSim 9000, Marketplace MCP 9100,
# Portfolio MCP 9101, Workspace MCP 9102, API 8000, Next.js on $PORT (default 7860).
# The Arq worker starts only when REDIS_URL is set. If any service exits, everything is stopped and
# the container exits non-zero so the platform restarts it.
set -u

cd "${APP_DIR:-/app}"
export PYTHONPATH="$PWD"
export PORT="${PORT:-7860}"

STATE_DIR="${STATE_DIR:-/home/user/state}"
mkdir -p "$STATE_DIR"
export CHECKPOINT_DB="${CHECKPOINT_DB:-$STATE_DIR/checkpoints.sqlite}"
export USERS_DB="${USERS_DB:-$STATE_DIR/users.sqlite}"
export AUDIT_LOG_PATH="${AUDIT_LOG_PATH:-$STATE_DIR/audit.jsonl}"

rand() { python -c "import secrets; print(secrets.token_urlsafe(32))"; }

# Secrets come from the Space secrets. Missing ones are generated per boot (sessions and stored
# OAuth tokens then do not survive a restart, and a warning is printed).
for name in MARKETPLACE_MCP_TOKEN WORKSPACE_MCP_TOKEN JWT_SECRET; do
  if [ -z "${!name:-}" ]; then
    export "$name"="$(rand)"
    echo "[start] WARNING: $name not set, generated for this boot only"
  fi
done
if [ -z "${TOKEN_ENCRYPTION_KEY:-}" ]; then
  TOKEN_ENCRYPTION_KEY="$(python -c 'from agent.security.tokens import new_key; print(new_key())')"
  export TOKEN_ENCRYPTION_KEY
  echo "[start] WARNING: TOKEN_ENCRYPTION_KEY not set, generated for this boot only"
fi

export MARKETPLACE_MODE="${MARKETPLACE_MODE:-mcp}"
export MARKETPLACE_MCP_URL="${MARKETPLACE_MCP_URL:-http://127.0.0.1:9100/mcp}"
export GIGSIM_URL="${GIGSIM_URL:-http://127.0.0.1:9000}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"

PIDS=()
NAMES=()

start() {
  local name="$1"; shift
  echo "[start] $name"
  "$@" &
  PIDS+=("$!")
  NAMES+=("$name")
}

wait_port() {  # wait_port <port> <seconds>
  local port="$1" tries="$2"
  for _ in $(seq 1 "$tries"); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then return 0; fi
    sleep 1
  done
  echo "[start] port $port did not open in ${tries}s"
  return 1
}

shutdown() {
  trap - TERM INT
  echo "[start] stopping services"
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null; done
  wait
}
trap 'shutdown; exit 143' TERM INT

start gigsim python -m uvicorn gigsim.app:app --host 127.0.0.1 --port 9000
wait_port 9000 60 || { shutdown; exit 1; }

MCP_HOST=127.0.0.1 MARKETPLACE_BACKEND=gigsim MARKETPLACE_MCP_PORT=9100 \
  start mcp-marketplace python -m mcp_servers.marketplace.server --http
MCP_HOST=127.0.0.1 WORKSPACE_MCP_PORT=9102 \
  start mcp-workspace python -m mcp_servers.workspace.server --http
FASTMCP_HOST=127.0.0.1 FASTMCP_PORT=9101 \
  start mcp-portfolio python -m mcp_servers.portfolio.server --http
wait_port 9100 60 || { shutdown; exit 1; }
wait_port 9102 60 || { shutdown; exit 1; }
wait_port 9101 120 || { shutdown; exit 1; }

start api python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
wait_port 8000 180 || { shutdown; exit 1; }

if [ -n "${REDIS_URL:-}" ]; then
  start worker arq worker.main.WorkerSettings
else
  echo "[start] REDIS_URL not set, worker skipped (background tasks run inline in the API)"
fi

# Next.js standalone server. API_URL was baked into the rewrites at build time (127.0.0.1:8000).
HOSTNAME=0.0.0.0 start web node /app/web/server.js

# Supervisor: block until the first service exits, then stop the rest.
wait -n
code=$?
for i in "${!PIDS[@]}"; do
  if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then echo "[start] ${NAMES[$i]} exited (code $code)"; fi
done
shutdown
exit "${code:-1}"
