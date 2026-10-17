#!/usr/bin/env bash
# Deploy the committed HEAD to the server: copy the source, build, restart, check.
#
#   NAMESAKE_HOST=user@host deploy/deploy.sh          deploy HEAD
#   NAMESAKE_HOST=user@host deploy/deploy.sh --env    also (re)write the server's .env
#   NAMESAKE_HOST=user@host deploy/deploy.sh --seed   also install the local cache
#
# Optional: NAMESAKE_DIR (default /opt/namesake), PROXY_NETWORK (the Caddy container's
# Docker network), NAMESAKE_URL (checked over HTTPS at the end, once Caddy has the site).
# First-time setup, the Caddy site block and rolling back are in deploy/README.md.
#
# --env builds the .env locally with deploy/make_env.py (no value is printed), sends it,
# and installs it with mode 600 only once it is complete. --seed installs var/cache.sqlite
# only while the server's cache holds no rows yet. Files inside the private cache folder
# are handled by deploy/prepare_var.py, run as root in a one-off container, so any ssh
# user that can run docker and write NAMESAKE_DIR can deploy. Saved listings are held to
# today's checks (app/agent/recheck.py) before the new version starts. Only committed
# changes are deployed. If any step fails, the previous source and image come back and
# the previous version keeps running, or is started again.
set -euo pipefail
HOST=${NAMESAKE_HOST:?set NAMESAKE_HOST=user@host}
DIR=${NAMESAKE_DIR:-/opt/namesake}
PROXY_NETWORK=${PROXY_NETWORK:-mexicoproj_default}
case "$DIR" in /*) ;; *) echo "✗ NAMESAKE_DIR must be an absolute path"; exit 2 ;; esac
cd "$(git rev-parse --show-toplevel)"

ENV=""; SEED=""
for arg in "$@"; do
  case "$arg" in
    --env) ENV=1 ;;
    --seed) SEED=1 ;;
    *) echo "unknown option $arg"; exit 2 ;;
  esac
done

# Every value that reaches a remote command is shell-quoted, and files travel over ssh
# into fixed names, so no path is ever parsed by a remote shell unquoted.
D=$(printf %q "$DIR")
NET=$(printf %q "$PROXY_NETWORK")
remote() { ssh "$HOST" "set -euo pipefail; cd $D; $1"; }
put() { ssh "$HOST" "umask 077; cat > $D/$1" < "$2"; }
# The previous source and image, kept as src.prev and namesake-app:prev until the new
# version is healthy. The upload is dropped either way.
roll_back() {
  remote "if [ -d src.prev ]; then rm -rf src && mv src.prev src; fi; rm -f upload/cache.sqlite
    if docker image inspect namesake-app:prev >/dev/null 2>&1; then docker tag namesake-app:prev namesake-app; fi"
}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

SHA=$(git rev-parse --short HEAD)
echo "→ Preparing $HOST:$DIR for $SHA"
ssh "$HOST" "mkdir -p $D && cd $D && if [ ! -d var ]; then mkdir var && chmod 700 var; fi && mkdir -p upload && chmod 700 upload" \
  || { echo "✗ $DIR is not writable by the ssh user: create it once as root (deploy/README.md)"; exit 1; }
put compose.yml deploy/compose.yml

if [ -n "$ENV" ]; then
  echo "→ Writing .env (values not shown)"
  subnets=$(ssh "$HOST" "docker network inspect $NET --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'" 2>/dev/null) || subnets=""
  [ -n "$subnets" ] || { echo "✗ Docker network $PROXY_NETWORK not found on the server"; exit 1; }
  # Built and checked locally first, so a missing value stops here with nothing sent.
  (umask 077; uv run --quiet python deploy/make_env.py --subnet "$subnets" --network "$PROXY_NETWORK" > "$work/env")
  put .env.new "$work/env"
  # A cut-off transfer fails put() above, so a complete file is one with every key.
  remote "for k in QLOO_API_KEY AGENT_BASE_URL AGENT_API_KEY AGENT_MODEL AGENT_API FORWARDED_ALLOW_IPS PROXY_NETWORK; do grep -q \"^\$k=.\" .env.new; done; chmod 600 .env.new; mv .env.new .env"
fi
remote "test -s .env" || { echo "✗ no .env on the server; run once with --env"; exit 1; }

if [ -n "$SEED" ]; then
  echo "→ Uploading the local cache"
  sqlite3 var/cache.sqlite ".backup '$work/cache.sqlite'"
  put upload/cache.sqlite "$work/cache.sqlite"
fi

echo "→ Copying the source"
ssh "$HOST" "rm -rf $D/src.new && mkdir $D/src.new"
git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $D/src.new"
remote "rm -rf src.prev; if [ -d src ]; then mv src src.prev; fi; mv src.new src
  if docker image inspect namesake-app >/dev/null 2>&1; then docker tag namesake-app namesake-app:prev; fi"

echo "→ Building"
if ! remote "docker compose build"; then
  echo "✗ The build failed; restoring the previous source. The running version is unchanged."
  roll_back
  exit 1
fi

echo "→ Preparing the cache folder"
seed_args=""
[ -n "$SEED" ] && seed_args="--seed /upload/cache.sqlite"
if ! remote "docker compose run --rm --no-deps --user root -v $D/upload:/upload:ro -v $D/src/deploy:/deploy:ro --entrypoint python app /deploy/prepare_var.py /app/var $seed_args"; then
  echo "✗ The cache folder could not be prepared; restoring the previous source. The running version is unchanged."
  roll_back
  exit 1
fi

echo "→ Re-checking saved listings against today's checks"
if ! remote "docker compose run --rm --no-deps app python -m app.agent.recheck"; then
  echo "✗ The recheck failed; restoring the previous source. The running version is unchanged."
  roll_back
  exit 1
fi

echo "→ Restarting"
tries=60
remote "docker compose up -d --remove-orphans" || tries=0

echo "→ Checking /health and that the cache is writable"
ok=""
for _ in $(seq 1 $tries); do
  # mode=rw opens the cache file prepare_var.py made sure of, and never creates one.
  if remote "docker compose exec -T app python -c \"import sqlite3, urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health'); c = sqlite3.connect('file:/app/var/cache.sqlite?mode=rw', uri=True); c.execute('BEGIN IMMEDIATE'); c.rollback()\"" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 2
done
if [ -z "$ok" ]; then
  echo "✗ The new version did not start, or was not healthy within 2 minutes. Recent logs:"
  remote "docker compose logs --tail=60 app" || true
  echo "→ Starting the previous version again"
  roll_back
  remote "if docker image inspect namesake-app:prev >/dev/null 2>&1; then docker compose up -d --no-build --remove-orphans; else echo 'no previous version to start'; fi" \
    || echo "✗ The previous version did not start either: check 'docker compose ps' on the server"
  exit 1
fi
remote "rm -rf src.prev upload/cache.sqlite"

if [ -n "${NAMESAKE_URL:-}" ]; then
  echo "→ Checking $NAMESAKE_URL/health through the proxy"
  curl -fsS --max-time 20 "$NAMESAKE_URL/health" >/dev/null \
    || { echo "✗ The app is running, but $NAMESAKE_URL does not answer: check the Caddy site block (deploy/README.md)"; exit 1; }
fi

# Only this project's leftover images, and never a reason to fail a good deploy.
remote "docker image prune -f --filter label=com.docker.compose.project=namesake >/dev/null 2>&1 || true; docker compose ps"
echo "✓ Deployed $SHA"
