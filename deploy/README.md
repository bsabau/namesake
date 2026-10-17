# Deploying Namesake

The demo runs as one container on a long-lived Linux host with Docker, behind a Caddy that already serves the host's ports 80 and 443 for another project. On the host:

```
/opt/namesake/
  compose.yml   copied from deploy/compose.yml on every deploy
  .env          keys and settings, mode 600, written by `deploy.sh --env`
  src/          the committed source of the running version
  var/          the SQLite cache, saved results and approvals: private, mode 700
```

The Qloo cache in `var/` holds Qloo response data. It stays on this host and is never committed or published.

## First deploy

1. **DNS.** Point the demo's name at the host: an `A` record, for example `namesake` → the host's IP, in the domain's DNS zone.
2. **The folder.** The ssh user needs to run `docker` and to write the deploy folder. Unless it is root, create the folder once as root: `sudo install -d -o "$USER" /opt/namesake` on the host (or set `NAMESAKE_DIR` to a folder it owns).
3. **Ship it**, from a clean checkout of the commit you want live:

   ```sh
   NAMESAKE_HOST=user@host deploy/deploy.sh --env --seed
   ```

   Leave `NAMESAKE_URL` out this first time: Caddy doesn't know the site until step 4. `--env` writes the host's `.env` from your local `.env` (the `AGENT_*` values) and `~/.qloo/config` (the Qloo key). `--seed` installs your local cache, so the start page's examples open instantly; it does so only while the host's cache holds no rows, and refuses after that. The script builds the image on the host, re-checks saved listings against today's checks, starts the container, and checks that `/health` answers and the cache is writable. Files inside the private `var/` are handled by `deploy/prepare_var.py` in a one-off root container, so the ssh user needs no root after step 2.
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

## Later deploys

```sh
NAMESAKE_HOST=deploy@host NAMESAKE_URL=https://namesake.example.com deploy/deploy.sh
```

Only committed changes are deployed. Every deploy re-checks the saved listings against today's checks (`app/agent/recheck.py`): one that passes stays, one that fails runs again when next opened. The source, `compose.yml`, `.env` and the image change together. If any step fails, the check through the proxy included, all four come back (the image as `namesake-app:prev`, the one the running container used): before the restart the running container is untouched, and after it the previous version is started again. To roll back on purpose, check out the earlier commit and deploy again.

## Settings worth knowing

- **`PROXY_NETWORK`**: the Caddy container's Docker network, which the app joins as `namesake`. It has no published port, so only the proxy reaches it.
- **`FORWARDED_ALLOW_IPS`** is set to that network's subnet, so the app trusts the visitor address Caddy forwards and per-visitor limits see real visitors. Caddy's own address changes when its container restarts, so a single IP would break silently. The cost: any container on that network could forge a visitor address and dodge the per-visitor limit; the daily caps still hold. On a host with one operator that is acceptable; on a shared host, give Caddy a fixed IP and use it instead.
- **The model and the Qloo key** come from `.env`. To change the model, edit the `AGENT_*` values in your local `.env` and deploy with `--env`.
