# Deploying Namesake

The demo runs as one container on a long-lived Linux host with Docker, behind a Caddy that already serves the host's ports 80 and 443 for another project. On the host:

```
/opt/namesake/
  compose.yml   copied from deploy/compose.yml on every deploy
  .env          keys and settings, mode 600, written by `deploy.sh --env`
  src/          the committed source of the running version
  var/          the SQLite cache, saved results and approvals, and visitors' workspaces: private, mode 700
```

The Qloo cache in `var/` holds Qloo response data. It stays on this host and is never committed or published.

## First deploy

1. **DNS.** Point the demo's name at the host: an `A` record, for example `namesake` → the host's IP, in the domain's DNS zone.
2. **The folder.** The ssh user needs to run `docker` and to write the deploy folder. Unless it is root, create the folder once as root: `sudo install -d -o "$USER" /opt/namesake` on the host (or set `NAMESAKE_DIR` to a folder it owns).
3. **Ship it**, from a clean checkout of the commit you want live:

   ```sh
   NAMESAKE_HOST=user@host PROXY_NETWORK=<the Caddy network> deploy/deploy.sh --env --seed
   ```

   Leave `NAMESAKE_URL` out this first time: Caddy doesn't know the site until step 4. `--env` writes the host's `.env` from your local `.env` (the `AGENT_*` values, and `GEOCODER_URL`, `QLOO_MIN_INTERVAL`, the `TYPESAFE_*` settings, `MAP_TILES_KEY` and the three caps on live work if set) and `~/.qloo/config` (the Qloo key). `--seed` installs your local cache, so the start page's examples open instantly; it does so only while the host's cache holds no rows, and refuses after that. The script builds the image on the host, re-checks saved listings against today's checks, starts the container, and checks that `/health` answers and the cache is writable. Files inside the private `var/` are handled by `deploy/prepare_var.py` in a one-off root container, so the ssh user needs no root after step 2.
4. **Caddy.** Append `deploy/Caddyfile.snippet` (with your domain) to the host's Caddyfile, then reload Caddy without restarting it:

   ```sh
   cp Caddyfile Caddyfile.bak-$(date +%Y%m%d%H%M%S)
   cat Caddyfile.snippet >> Caddyfile
   docker exec <caddy-container> caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   docker exec <caddy-container> caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
   ```

   Caddy gets the certificate on the first request. If the Caddyfile belongs to another project's git checkout, that project's `git pull` stops whenever its own Caddyfile changes, until the local edit is merged; note it in that project.
5. Run `deploy.sh` once more with `NAMESAKE_URL` set: it now also checks the site through the proxy.

## Automatic deploys

Changes reach `main` through a pull request. CI (`.github/workflows/ci.yml`) runs ruff and the tests on every pull request; once a merge to `main` passes CI, `.github/workflows/deploy.yml` runs `deploy.sh` against the host, with the check through the proxy. Only `main`'s newest commit is deployed: a run that finds a newer one skips, since that one's own run deploys it. It never runs `--env` or `--seed`: the Qloo and model keys stay in the host's `.env`, and GitHub holds only what reaches the host.

- **On the host:** a `deploy` user in the `docker` group owns `/opt/namesake` (except `var/`, which belongs to the app). Its `authorized_keys` holds the GitHub key, with `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty` (no forced `command=`: `deploy.sh` runs many different commands), and the author's own key. Docker access is as good as root on the host, which is why it is a user of its own: removing that key line revokes GitHub's access without touching anything else.
- **On GitHub:** the `production` environment, which only `main` may deploy from, holds `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` (the host's pinned key, so a changed host key stops the deploy) and `DEPLOY_HOST`.
- **By hand:** "Run workflow" on the Deploy workflow, on `main`, redeploys `main` as it is, without waiting for CI. A local deploy uses the same user: `NAMESAKE_HOST=deploy@host`. Changing `.env` (`--env`) or seeding (`--seed`) is done locally.

## Watching the demo

The demo must stay up, unattended, through judging: 2 November 12:00 to 5 November 09:00 US Eastern.

- **Every hour**, `.github/workflows/watch.yml` runs `deploy/watch.py` against the live site. It checks `/health`, that the start page (its JSON and the page itself) lists every example, and that each example opens its saved result in the story skin. Only public pages are opened, so it costs no Qloo or model call and needs no secrets; it also never starts a run, so a dead Qloo key or a model outage does not fail it (those show in `docker compose logs app`). A failure is checked again a minute later, so a deploy's restart passes. If it fails again, the run fails, and GitHub emails whoever last edited the schedule. Check that "Actions" notifications are on in GitHub's settings. "Run workflow" checks at once, and `python3 deploy/watch.py https://namesake.bogdansabau.eu --examples 4` does the same from any machine.
- **How close the demo comes to its caps:** `docker compose exec app python -m app.limits` on the host prints each of the last 14 days' live runs and new areas (UTC) against the daily caps, quiet days as zero, with the per-visitor cap on the line above (it lives in memory and is not counted). To change a cap, set `LIVE_RUNS_PER_DAY`, `LIVE_RUNS_PER_VISITOR_PER_HOUR` or `NEW_LOCATIONS_PER_DAY` in your local `.env` and deploy with `--env`; without them, or left empty, the host keeps the defaults (60, 6 and 10). For judging, the author raised all three far above the defaults on 22 October, so that judges are not refused, even several judging through an agent from one address. The cost is that only those raised caps stand between a looping visitor and the model fallbacks' spend, or a Qloo key refused for its rate. Usage is read with `app.limits` after the first judging day (2 November), and the caps come down if it spikes.

## Later deploys

```sh
NAMESAKE_HOST=deploy@host NAMESAKE_URL=https://namesake.example.com deploy/deploy.sh
```

Only committed changes are deployed. Every deploy re-checks the saved listings against today's checks (`app/agent/recheck.py`): one that passes stays, one that fails runs again when next opened. The source, `compose.yml`, `.env` and the image change together. If any step fails, the check through the proxy included, all four come back (the image as `namesake-app:prev`, the one the running container used): before the restart the running container is untouched, and after it the previous version is started again. To roll back on purpose, check out the earlier commit and deploy again.

## Who tends to like each name's title

Listings written since decision 31 carry Qloo's audience for each name's title. To add it to listings saved before, once, on the host (about one call per title not asked before, spaced 10 seconds apart; titles repeat across areas, so the examples take a few minutes):

```sh
ssh deploy@host 'cd /opt/namesake && docker compose exec -T app python -m app.audience'
```

It skips listings saved before the checks last changed (their next run rewrites them) and writes only onto a listing that no run has rewritten meanwhile. A title Qloo has nothing for is left out and asked again by a later run.

## Upgrading saved profiles

When a change raises the profile version (`PROFILE_VERSION` in `app/profile.py`), or changes what a saved profile must have (`needs_finishing` in the same file, such as the comparison screen of decision 18), saved profiles keep working as they were until upgraded or until a visitor's run finishes them. Upgrade them on the host, paced under the key's limit, the examples' areas first:

```sh
ssh deploy@host 'cd /opt/namesake && docker compose exec -T app python -m app.upgrade_profiles --only park-slope,astoria'
```

It prints each profile it upgraded or left as it was; run it again later without `--only` for the rest, including Austin and the areas visitors typed.

## Building the examples

The start page's "Read a finished story" links (`EXAMPLES` in `app/views/build.py`) show once their results are saved in the host's cache. A new example is built on the host, live (Qloo and the model), paced under the key's limit, after backing up the cache; `--only` takes the areas to build. The image holds no `scripts/`, so the source's copy is mounted into a one-off container:

```sh
ssh deploy@host 'cd /opt/namesake && docker compose run --rm --no-deps -e QLOO_MIN_INTERVAL=10 -v /opt/namesake/src/scripts:/app/scripts:ro app python scripts/precompute_examples.py --only astoria'
```

`--all` builds every animal in the roster, each litter named as a set, in every preset area (or those in `--only`), so judges open saved listings instead of waiting minutes for a live run; what is saved and current is skipped. `--dry-run` lists what it would build, from the cache, with no model and no Qloo. A full run is about 50 listings and takes an hour or more, so it runs detached, after a dated backup of the cache. It paces Qloo at the host's `QLOO_MIN_INTERVAL` (2 since Qloo raised the limits on 21 October); add `-e QLOO_MIN_INTERVAL=10` if Qloo starts refusing.

```sh
ssh deploy@host 'cd /opt/namesake && docker compose exec -T app python -c "import sqlite3, time; sqlite3.connect(\"var/cache.sqlite\").backup(sqlite3.connect(time.strftime(\"var/cache-backup-%Y%m%d-%H%M.sqlite\")))"'
ssh deploy@host 'cd /opt/namesake && docker compose run --rm --no-deps -v /opt/namesake/src/scripts:/app/scripts:ro app python scripts/precompute_examples.py --all --dry-run'
ssh deploy@host 'cd /opt/namesake && docker compose run -d --no-deps --name namesake-precompute -v /opt/namesake/src/scripts:/app/scripts:ro app python scripts/precompute_examples.py --all'
ssh deploy@host 'docker logs -f namesake-precompute'
ssh deploy@host 'docker rm namesake-precompute'    # once it has finished, before running it again
```

## Placing saved profiles' venues on the map

Each new run places its profile's suggested venues once, from OpenStreetMap (Photon), after the profile is saved (decision 4, revised). Profiles saved before that are placed on the host, about a second a lookup, with no Qloo call:

```sh
ssh deploy@host 'cd /opt/namesake && docker compose exec -T app python -m app.venue_points'
```

## Settings worth knowing

- **`PROXY_NETWORK`**: the Caddy container's Docker network, which the app joins as `namesake`. It has no published port, so only the proxy reaches it. The first deploy needs it; later deploys (CI's included) read it from the server's `.env`, where `--env` writes it.
- **`FORWARDED_ALLOW_IPS`** is set to that network's subnet, so the app trusts the visitor address Caddy forwards and per-visitor limits see real visitors. Caddy's own address changes when its container restarts, so a single IP would break silently. The cost: any container on that network could forge a visitor address and dodge the per-visitor limit; the daily caps still hold. On a host with one operator that is acceptable; on a shared host, give Caddy a fixed IP and use it instead.
- **The model and the Qloo key** come from `.env`. To change the model or its fallbacks, edit the `AGENT_*` values (`AGENT_FALLBACK_1_*`, `AGENT_FALLBACK_2_*` for the fallbacks) in your local `.env` and deploy with `--env`.
- **`MAP_TILES_KEY`** (optional) is a CARTO basemap key for the story skin's maps. It reaches the visitor's browser, which is where tile requests come from, so restrict it to the site's domain in CARTO's dashboard. Without it the maps use OpenStreetMap's standard tiles.
