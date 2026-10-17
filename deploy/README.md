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
2. **Ship it**, from a clean checkout of the commit you want live:

   ```sh
   NAMESAKE_HOST=user@host deploy/deploy.sh --env --seed
   ```

   Leave `NAMESAKE_URL` out this first time: Caddy doesn't know the site until step 3. `--env` writes the host's `.env` from your local `.env` (the `AGENT_*` values) and `~/.qloo/config` (the Qloo key). `--seed` installs your local cache, so the start page's examples open instantly; it does so only while the host's cache holds no saved results, and refuses after that. The script builds the image on the host, starts the container, and checks that `/health` answers and the cache is writable. The ssh user needs to run `docker`, not to be root: files inside the private `var/` are handled by `deploy/prepare_var.py` in a one-off root container.
3. **Caddy.** Append `deploy/Caddyfile.snippet` (with your domain) to the host's Caddyfile, then reload Caddy without restarting it:

   ```sh
   cp Caddyfile Caddyfile.bak-$(date +%Y%m%d%H%M%S)
   cat Caddyfile.snippet >> Caddyfile
   docker exec <caddy-container> caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   docker exec <caddy-container> caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
   ```

   Caddy gets the certificate on the first request. If the Caddyfile belongs to another project's git checkout, that project's `git pull` stops whenever its own Caddyfile changes, until the local edit is merged; note it in that project.
4. Run `deploy.sh` once more with `NAMESAKE_URL` set: it now also checks the site through the proxy.

## Later deploys

```sh
NAMESAKE_HOST=user@host NAMESAKE_URL=https://namesake.example.com deploy/deploy.sh
```

Only committed changes are deployed. If the build fails, the previous source is restored and the running container is untouched. To roll back, check out the earlier commit and deploy again.

## Settings worth knowing

- **`PROXY_NETWORK`**: the Caddy container's Docker network, which the app joins as `namesake`. It has no published port, so only the proxy reaches it.
- **`FORWARDED_ALLOW_IPS`** is set to that network's subnet, so the app trusts the visitor address Caddy forwards and per-visitor limits see real visitors. Caddy's own address changes when its container restarts, so a single IP would break silently. The cost: any container on that network could forge a visitor address and dodge the per-visitor limit; the daily caps still hold. On a host with one operator that is acceptable; on a shared host, give Caddy a fixed IP and use it instead.
- **The model and the Qloo key** come from `.env`. To change the model, edit the `AGENT_*` values in your local `.env` and deploy with `--env`.
