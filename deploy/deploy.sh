#!/usr/bin/env bash
# Deploy the committed HEAD to the server: copy the source, build, restart, check.
#
#   NAMESAKE_HOST=user@host deploy/deploy.sh          deploy HEAD
#   NAMESAKE_HOST=user@host deploy/deploy.sh --env    also (re)write the server's .env
#   NAMESAKE_HOST=user@host deploy/deploy.sh --seed   also install the local cache
#
# Optional: NAMESAKE_DIR (default /opt/namesake), PROXY_NETWORK (the Caddy container's
# Docker network; needed on the first deploy, read from the server's .env after),
# NAMESAKE_URL (checked over HTTPS at the end, once Caddy has the site),
# NAMESAKE_PREV_FROM_TAG=1 (see the swap below).
# First-time setup, the Caddy site block and rolling back are in deploy/README.md.
#
# --env builds the .env locally with deploy/make_env.py (no value is printed), sends it,
# and installs it with mode 600 only once it is complete. --seed installs var/cache.sqlite
# only while the server's cache holds no rows yet. Files inside the private cache folder
# are handled by deploy/prepare_var.py, run as root in a one-off container, so any ssh
# user that can run docker and write NAMESAKE_DIR can deploy. Saved listings are held to
# today's checks (app/agent/recheck.py) before the new version starts. Only committed
# changes are deployed. The source, compose.yml, .env and the image change together, and
# if any step fails, including the check through the proxy, all four come back and the
# previous version keeps running, or is started again.
set -euo pipefail
HOST=${NAMESAKE_HOST:?set NAMESAKE_HOST=user@host}
DIR=${NAMESAKE_DIR:-/opt/namesake}
case "$DIR" in /*) ;; *) echo "✗ NAMESAKE_DIR must be an absolute path"; exit 2 ;; esac
# The Caddy container's Docker network: as given, else the one the server's .env names
# (written there by the first --env deploy), so CI never needs it and no project's
# network name sits in this script.
if [ -z "${PROXY_NETWORK:-}" ]; then
  ssh "$HOST" true </dev/null || { echo "✗ cannot reach $HOST over ssh"; exit 1; }
  PROXY_NETWORK=$(ssh "$HOST" "sed -n 's/^PROXY_NETWORK=//p' $(printf %q "$DIR")/.env 2>/dev/null" </dev/null | head -n 1 | tr -d '[:space:]') || PROXY_NETWORK=""
fi
[ -n "$PROXY_NETWORK" ] || { echo "✗ set PROXY_NETWORK to the Caddy container's Docker network: the server's .env does not name one (a first deploy, or one from before --env wrote it)"; exit 2; }
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
# The previous version, kept as src.prev, compose.yml.prev, .env.prev (when --env
# replaced it) and the image namesake-app:prev until the new one is healthy. The upload
# is dropped either way.
roll_back() {
  remote "if [ -d src.prev ]; then rm -rf src && mv src.prev src; fi
    if [ -f compose.yml.prev ]; then mv compose.yml.prev compose.yml; fi
    if [ -f .env.prev ]; then mv .env.prev .env; fi
    rm -f upload/cache.sqlite
    if docker image inspect namesake-app:prev >/dev/null 2>&1; then docker tag namesake-app:prev namesake-app; fi
    rm -f .deploying"
}
# After the new container started: back to the previous version, and start it again.
start_previous() {
  echo "→ Starting the previous version again"
  roll_back
  remote "if docker image inspect namesake-app:prev >/dev/null 2>&1; then docker compose up -d --no-build --remove-orphans; else echo 'no previous version to start'; fi" \
    || echo "✗ The previous version did not start either: check 'docker compose ps' on the server"
  exit 1
}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

SHA=$(git rev-parse --short HEAD)
echo "→ Preparing $HOST:$DIR for $SHA"
ssh "$HOST" true || { echo "✗ cannot reach $HOST over ssh"; exit 1; }
ssh "$HOST" "mkdir -p $D && cd $D && if [ ! -d var ]; then mkdir var && chmod 700 var; fi && mkdir -p upload && chmod 700 upload" \
  || { echo "✗ $DIR is not writable by the ssh user: create it once as root (deploy/README.md)"; exit 1; }
# .deploying marks a deploy between its swap and its end. One that stopped there (ssh
# dropped, laptop closed) left its backups: go back to that version first, so they are
# never overwritten.
if remote "[ -e .deploying ]"; then
  echo "→ An earlier deploy did not finish; restoring the version before it first"
  roll_back || { echo "✗ Could not restore the version before it: see src.prev, compose.yml.prev and .env.prev on the server"; exit 1; }
  remote "if docker image inspect namesake-app:prev >/dev/null 2>&1; then docker compose up -d --no-build --remove-orphans; fi" \
    || { echo "✗ The restored version did not start: check 'docker compose ps' on the server"; exit 1; }
fi
# New files wait as *.new until the source is swapped; leftovers of a stopped run go first.
remote "rm -rf compose.yml.new .env.new src.new"
put compose.yml.new deploy/compose.yml

if [ -n "$ENV" ]; then
  echo "→ Writing .env (values not shown)"
  subnets=$(ssh "$HOST" "docker network inspect $NET --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'" 2>/dev/null) || subnets=""
  [ -n "$subnets" ] || { echo "✗ Docker network $PROXY_NETWORK not found on the server"; exit 1; }
  # Built and checked locally first, so a missing value stops here with nothing sent.
  (umask 077; uv run --quiet python deploy/make_env.py --subnet "$subnets" --network "$PROXY_NETWORK" > "$work/env")
  put .env.new "$work/env"
  # A cut-off transfer fails put() above, so a complete file is one with every key.
  # AGENT_BASE_URL is left out: Anthropic's own API needs none, and make_env.py checks it.
  remote "for k in QLOO_API_KEY AGENT_API_KEY AGENT_MODEL AGENT_API FORWARDED_ALLOW_IPS PROXY_NETWORK; do grep -q \"^\$k=.\" .env.new; done; chmod 600 .env.new"
fi
remote "test -s .env || test -s .env.new" || { echo "✗ no .env on the server; run once with --env"; exit 1; }

if [ -n "$SEED" ]; then
  echo "→ Uploading the local cache"
  sqlite3 var/cache.sqlite ".backup '$work/cache.sqlite'"
  put upload/cache.sqlite "$work/cache.sqlite"
fi

echo "→ Copying the source"
ssh "$HOST" "mkdir $D/src.new"
git archive --format=tar HEAD | ssh "$HOST" "tar -x -C $D/src.new"
# Backups left by a deploy that finished but stopped during its cleanup are stale. The
# image to come back to is the one the app's container uses, running or stopped, found by
# Compose's labels so no compose file or .env is read; with no app container, the current
# tag. Docker's containerd image store can prune an image a container still runs. Then the
# current tag may be a build that never ran, so the deploy stops unless
# NAMESAKE_PREV_FROM_TAG=1 says that tag is a fit rollback image.
PREV_FROM_TAG=""; [ "${NAMESAKE_PREV_FROM_TAG:-}" = 1 ] && PREV_FROM_TAG=1
swap="rm -rf src.prev compose.yml.prev .env.prev
  app=\$(docker ps -aq --filter label=com.docker.compose.project=namesake --filter label=com.docker.compose.service=app --filter label=com.docker.compose.oneoff=False | head -n 1)
  img=\$([ -n \"\$app\" ] && docker inspect -f '{{.Image}}' \"\$app\" || true)
  if [ -n \"\$img\" ] && docker image inspect \"\$img\" >/dev/null 2>&1; then docker tag \"\$img\" namesake-app:prev
  elif [ -n \"\$app\" ] && [ -z '$PREV_FROM_TAG' ]; then
    echo '✗ The running image is gone (pruned), so there is nothing tested to roll back to. Check that namesake-app is a build of the running version, then run again with NAMESAKE_PREV_FROM_TAG=1.'; exit 1
  elif docker image inspect namesake-app >/dev/null 2>&1; then docker tag namesake-app namesake-app:prev; fi
  touch .deploying
  if [ -d src ]; then mv src src.prev; fi; mv src.new src
  if [ -f compose.yml ]; then mv compose.yml compose.yml.prev; fi; mv compose.yml.new compose.yml
  if [ -f .env.new ]; then if [ -f .env ]; then mv .env .env.prev; fi; mv .env.new .env; fi"
if ! remote "$swap"; then
  echo "✗ The swap did not finish; restoring the previous files. The running version is unchanged."
  roll_back
  exit 1
fi

echo "→ Building"
# Capped, so a hung build ends here with time left to roll back (.github/workflows).
if ! remote "timeout 1500 docker compose build"; then
  echo "✗ The build failed or took over 25 minutes; restoring the previous source. The running version is unchanged."
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
ok=""
# Only a container that `up` just started is checked: if `up` fails, the old one may
# still answer.
if remote "docker compose up -d --remove-orphans"; then
  echo "→ Checking /health and that the cache is writable"
  for _ in $(seq 1 60); do
    # mode=rw opens the cache file prepare_var.py made sure of, and never creates one.
    if remote "docker compose exec -T app python -c \"import sqlite3, urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health'); c = sqlite3.connect('file:/app/var/cache.sqlite?mode=rw', uri=True); c.execute('BEGIN IMMEDIATE'); c.rollback()\"" >/dev/null 2>&1; then
      ok=1
      break
    fi
    sleep 2
  done
fi
if [ -z "$ok" ]; then
  echo "✗ The new version did not start, or was not healthy within 2 minutes. Recent logs:"
  remote "docker compose logs --tail=60 app" || true
  start_previous
fi

public=0
if [ -n "${NAMESAKE_URL:-}" ]; then
  echo "→ Checking $NAMESAKE_URL/health through the proxy"
  answered=""
  for _ in $(seq 1 10); do
    public=0
    curl -fsS --max-time 20 "$NAMESAKE_URL/health" >/dev/null || public=$?
    [ "$public" -eq 0 ] && break
    [ "$public" -eq 22 ] && answered=1
    sleep 3
  done
  # 22: the proxy answered with an error, so it cannot reach this version; a brief 502
  # right after the restart is retried, and a later failure to connect from here does not
  # hide it. Without one (no DNS, no connection from here) it may be this machine's
  # network, not the deploy.
  if [ "$public" -ne 0 ] && [ -n "$answered" ]; then
    echo "✗ The app is running, but $NAMESAKE_URL answers with an error: check the Caddy site block and PROXY_NETWORK (deploy/README.md)"
    start_previous
  fi
fi
remote "rm -f .deploying; rm -rf src.prev compose.yml.prev .env.prev upload/cache.sqlite"

# Only this project's leftover images, and never a reason to fail a good deploy.
remote "docker image prune -f --filter label=com.docker.compose.project=namesake >/dev/null 2>&1 || true; docker compose ps"
if [ "$public" -ne 0 ]; then
  echo "✗ Deployed $SHA and healthy on the server, but $NAMESAKE_URL could not be reached from here (curl exit $public): check it from another network"
  exit 1
fi
echo "✓ Deployed $SHA"
