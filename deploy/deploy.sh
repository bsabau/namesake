#!/usr/bin/env bash
# Deploy the committed HEAD to the server: copy the source, build, restart, check.
#
#   NAMESAKE_HOST=user@host deploy/deploy.sh          deploy HEAD
#   NAMESAKE_HOST=user@host deploy/deploy.sh --env    also (re)write the server's .env
#   NAMESAKE_HOST=user@host deploy/deploy.sh --seed   also copy the local cache (first deploy)
#
# Optional: NAMESAKE_DIR (default /opt/namesake), PROXY_NETWORK (the Caddy container's
# Docker network), NAMESAKE_URL (checked over HTTPS at the end). First-time setup, the
# Caddy site block and how to roll back are in deploy/README.md.
#
# --env builds the .env from this machine's .env (AGENT_*) and ~/.qloo/config with
# deploy/make_env.py, sends it over ssh, and installs it with mode 600 only once it is
# complete; no value is printed. --seed copies var/cache.sqlite once: after that the
# server's cache grows on its own and is never overwritten. Uncommitted changes are not
# deployed, and a failed build leaves the running version and its source in place.
set -euo pipefail
HOST=${NAMESAKE_HOST:?set NAMESAKE_HOST=user@host}
DIR=${NAMESAKE_DIR:-/opt/namesake}
PROXY_NETWORK=${PROXY_NETWORK:-mexicoproj_default}
cd "$(git rev-parse --show-toplevel)"

# Every value that reaches a remote command is shell-quoted.
D=$(printf %q "$DIR")
NET=$(printf %q "$PROXY_NETWORK")
remote() { ssh "$HOST" "set -euo pipefail; cd $D; $1"; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

SHA=$(git rev-parse --short HEAD)
echo "→ Preparing $HOST:$DIR for $SHA"
ssh "$HOST" "mkdir -p $D/var && chmod 700 $D/var"
scp -q deploy/compose.yml "$HOST:$DIR/compose.yml"

for arg in "$@"; do
  case "$arg" in
    --env)
      echo "→ Writing .env (values not shown)"
      subnet=$(ssh "$HOST" "docker network inspect $NET --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}'")
      [ -n "$subnet" ] || { echo "✗ Docker network $PROXY_NETWORK not found on the server"; exit 1; }
      # Built locally first, so a missing value stops here with nothing sent.
      (umask 077; uv run --quiet python deploy/make_env.py --subnet "$subnet" --network "$PROXY_NETWORK" > "$work/env")
      ssh "$HOST" "umask 077; cat > $D/.env.new" < "$work/env"
      remote "grep -q '^QLOO_API_KEY=.' .env.new && grep -q '^AGENT_API_KEY=.' .env.new && chmod 600 .env.new && mv .env.new .env"
      ;;
    --seed)
      echo "→ Seeding the server's cache from var/cache.sqlite"
      remote "test ! -e var/cache.sqlite" || { echo "✗ the server already has a cache; not overwriting"; exit 1; }
      sqlite3 var/cache.sqlite ".backup '$work/cache.sqlite'"
      scp -q "$work/cache.sqlite" "$HOST:$DIR/var/cache.sqlite.upload"
      # mv within one folder is atomic; an interrupted upload leaves only the .upload file.
      remote "test ! -e var/cache.sqlite && mv var/cache.sqlite.upload var/cache.sqlite"
      ;;
    *) echo "unknown option $arg"; exit 2 ;;
  esac
done
remote "test -s .env" || { echo "✗ no .env on the server; run once with --env"; exit 1; }

echo "→ Copying the source"
ssh "$HOST" "rm -rf $D/src.new && mkdir $D/src.new"
git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $D/src.new"
remote "rm -rf src.prev; if [ -d src ]; then mv src src.prev; fi; mv src.new src"

echo "→ Building"
if ! remote "docker compose build"; then
  echo "✗ The build failed; restoring the previous source. The running version is unchanged."
  remote "if [ -d src.prev ]; then rm -rf src && mv src.prev src; fi"
  exit 1
fi

echo "→ Restarting"
# The app runs as the image's 'namesake' user, whatever user ssh logs in as, so the
# private cache folder is handed to it before the app starts.
remote "docker compose run --rm --no-deps --user root --entrypoint sh app -c 'chown -R namesake: /app/var && chmod 700 /app/var'"
remote "docker compose up -d --remove-orphans"

echo "→ Checking /health and that the cache is writable"
ok=""
for _ in $(seq 1 60); do
  if remote "docker compose exec -T app python -c \"import sqlite3, urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health'); c = sqlite3.connect('/app/var/cache.sqlite'); c.execute('BEGIN IMMEDIATE'); c.rollback()\"" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
if [ -z "$ok" ]; then
  echo "✗ Not healthy within 2 minutes. Recent logs:"
  remote "docker compose logs --tail=60 app"
  exit 1
fi

if [ -n "${NAMESAKE_URL:-}" ]; then
  echo "→ Checking $NAMESAKE_URL/health through the proxy"
  curl -fsS --max-time 20 "$NAMESAKE_URL/health" >/dev/null \
    || { echo "✗ The app is up but $NAMESAKE_URL does not answer: check the Caddy site block (deploy/README.md)"; exit 1; }
fi

# Only this project's leftover images; the host may run other projects.
remote "rm -rf src.prev; docker image prune -f --filter label=com.docker.compose.project=namesake >/dev/null; docker compose ps"
echo "✓ Deployed $SHA"
