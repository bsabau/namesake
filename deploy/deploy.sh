#!/usr/bin/env bash
# Deploy the committed HEAD to the server: copy the source, build, restart, wait for health.
#
#   NAMESAKE_HOST=user@host deploy/deploy.sh          deploy HEAD
#   NAMESAKE_HOST=user@host deploy/deploy.sh --env    also (re)write the server's .env
#   NAMESAKE_HOST=user@host deploy/deploy.sh --seed   also copy the local cache (first deploy)
#
# --env builds the server's .env from this machine's .env (AGENT_*) and ~/.qloo/config
# (the Qloo key), straight over ssh with mode 600; no value is printed. --seed copies
# var/cache.sqlite once: after that the server's cache grows on its own and is never
# overwritten. Uncommitted changes are not deployed.
set -euo pipefail
HOST=${NAMESAKE_HOST:?set NAMESAKE_HOST=user@host}
DIR=${NAMESAKE_DIR:-/opt/namesake}
PROXY_NETWORK=${PROXY_NETWORK:-mexicoproj_default}
cd "$(git rev-parse --show-toplevel)"

echo "→ Copying $(git rev-parse --short HEAD) to $HOST:$DIR"
ssh "$HOST" "mkdir -p $DIR/var && rm -rf $DIR/src.new && mkdir $DIR/src.new"
git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $DIR/src.new && rm -rf $DIR/src && mv $DIR/src.new $DIR/src"
scp -q deploy/compose.yml "$HOST:$DIR/compose.yml"

for arg in "$@"; do
  case "$arg" in
    --env)
      echo "→ Writing $DIR/.env (values not shown)"
      subnet=$(ssh "$HOST" "docker network inspect $PROXY_NETWORK --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'")
      PROXY_NETWORK=$PROXY_NETWORK SUBNET=$subnet uv run --no-project python - <<'PY' | ssh "$HOST" "umask 077 && cat > $DIR/.env"
import os, pathlib, re
local = dict(re.findall(r"^([A-Z_]+)=(.*)$", pathlib.Path(".env").read_text(), re.M))
qloo = dict(re.findall(r"^\s*(\w+)\s*[=:]\s*\"?([^\"\n]*)\"?", (pathlib.Path.home() / ".qloo/config").read_text(), re.M))
lines = {
    "QLOO_API_KEY": qloo["api_key"],
    "QLOO_BASE_URL": "https://hackathon.api.qloo.com",
    "QLOO_TRUSTED_BASE_URL": "https://hackathon.api.qloo.com",
    **{k: v for k, v in local.items() if k.startswith("AGENT_")},
    "ALLOW_LIVE_QLOO": "true",
    # Caddy reaches the app from this Docker network; trust its forwarded client address.
    "FORWARDED_ALLOW_IPS": os.environ["SUBNET"],
    "PROXY_NETWORK": os.environ["PROXY_NETWORK"],
}
print("\n".join(f"{k}={v}" for k, v in lines.items()))
PY
      ;;
    --seed)
      echo "→ Seeding the server's cache from var/cache.sqlite"
      tmp=$(mktemp -d)/cache.sqlite
      sqlite3 var/cache.sqlite ".backup '$tmp'"
      ssh "$HOST" "test ! -e $DIR/var/cache.sqlite" || { echo "✗ the server already has a cache; not overwriting"; exit 1; }
      scp -q "$tmp" "$HOST:$DIR/var/cache.sqlite"
      rm -f "$tmp"
      ;;
    *) echo "unknown option $arg"; exit 2 ;;
  esac
done

echo "→ Building and restarting"
ssh "$HOST" "cd $DIR && docker compose up --build -d --remove-orphans"

echo "→ Waiting for /health"
for _ in $(seq 1 60); do
  if ssh "$HOST" "cd $DIR && docker compose exec -T app python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')\"" >/dev/null 2>&1; then
    ssh "$HOST" "docker image prune -f >/dev/null 2>&1 || true; cd $DIR && docker compose ps"
    echo "✓ Deployed $(git rev-parse --short HEAD)"
    exit 0
  fi
  sleep 2
done
echo "✗ No healthy answer within 2 minutes. Recent logs:"
ssh "$HOST" "cd $DIR && docker compose logs --tail=60 app"
exit 1
