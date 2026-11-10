"""Build the server's .env from this machine's config, for `deploy/deploy.sh --env`.

Prints the file to stdout, which deploy.sh pipes straight to the server; it never
prints a value anywhere else. A missing or empty value stops it with the variable's
name only, before anything is sent.

    uv run python deploy/make_env.py --subnet 172.30.0.0/24 --network proxy --address 172.30.0.2
"""

import argparse
import ipaddress
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

QLOO_BASE = "https://hackathon.api.qloo.com"
# Settings from the local .env that the host takes as they are, besides the AGENT_* ones.
# TYPESAFE_API_KEY is optional: without it the classifier is off (decision 20).
# MAP_TILES_KEY is optional: without it the maps use OpenStreetMap's tiles (decision 24).
# The limits on live work are optional too: without them, or left empty, the host keeps
# the defaults in app/config.py. Any other value must be a whole number above zero: text
# would stop the app from starting, and zero would quietly switch live runs off.
SHARED = (
    "GEOCODER_URL",
    "QLOO_MIN_INTERVAL",
    "LIVE_RUNS_PER_VISITOR_PER_HOUR",
    "LIVE_RUNS_PER_DAY",
    "NEW_LOCATIONS_PER_DAY",
    "TYPESAFE_API_KEY",
    "TYPESAFE_MODEL",
    "TYPESAFE_BASE_URL",
    "MAP_TILES_KEY",
)
NUMBERS = ("LIVE_RUNS_PER_VISITOR_PER_HOUR", "LIVE_RUNS_PER_DAY", "NEW_LOCATIONS_PER_DAY")
REQUIRED = ("QLOO_API_KEY", "AGENT_BASE_URL", "AGENT_API_KEY", "AGENT_MODEL", "AGENT_API")


class MissingValue(Exception):
    pass


def qloo_key(config: Path) -> str:
    """The api_key from the harness's ~/.qloo/config ("api_key = ..." or "api_key: ...")."""
    if not config.is_file():
        raise MissingValue(f"QLOO_API_KEY: {config} not found")
    match = re.search(r"^\s*api_key\s*[=:]\s*[\"']?([^\"'\s#]+)", config.read_text(), re.M)
    if match is None:
        raise MissingValue(f"QLOO_API_KEY: no api_key in {config}")
    return match.group(1)


def proxy_subnet(subnets: str) -> str:
    """The first IPv4 subnet of the proxy network. Docker lists every subnet, IPv6 too,
    and uvicorn silently ignores a value it cannot parse, so only a valid one is kept."""
    for item in subnets.split():
        try:
            network = ipaddress.ip_network(item)
        except ValueError:
            continue
        if network.version == 4:
            return str(network)
    raise MissingValue(f"FORWARDED_ALLOW_IPS: no IPv4 subnet in {subnets!r}")


def proxy_address(address: str, subnet: str) -> str:
    """The proxy's own fixed address, checked to lie on its network. Trusting it alone
    means no other container on that network can forge a visitor's address."""
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        raise MissingValue(f"PROXY_ADDRESS: not an IP address: {address!r}") from None
    if ip.version != 4 or ip not in ipaddress.ip_network(subnet):
        raise MissingValue(f"PROXY_ADDRESS: {ip} is not on the proxy network {subnet}")
    return str(ip)


def proxy_holder(members: str, address: str) -> str:
    """The container that holds the proxy's address, refused unless it is the proxy: running
    and publishing HTTPS on the host. A mistyped address that lands on another app would
    otherwise make Namesake trust that app's forged visitor addresses.

    `members` is one line per container on the network, as deploy.sh reads it from the
    server: name, address/prefix, running (true or false), published ports ("443/tcp,...")."""
    for line in members.splitlines():
        name, cidr, running, ports = [*line.split(), "", "", "", ""][:4]
        if cidr.split("/")[0] != address:
            continue
        if running != "true":
            raise MissingValue(f"PROXY_ADDRESS: {name} holds {address} but is not running")
        if "443/tcp" not in ports.split(","):
            raise MissingValue(
                f"PROXY_ADDRESS: {name} holds {address} but publishes no HTTPS port: not the proxy"
            )
        return name
    raise MissingValue(f"PROXY_ADDRESS: no container on the proxy network holds {address}")


def build_env(
    local_env: Path, qloo_config: Path, subnet: str, network: str, address: str = ""
) -> dict[str, str]:
    subnet = proxy_subnet(subnet)
    # The proxy's fixed address when it has one (host-proxy gives Caddy 172.30.0.2),
    # else the whole subnet, for a proxy whose address changes when it restarts.
    trusted = {"PROXY_ADDRESS": proxy_address(address, subnet)} if address.strip() else {}
    local = {
        k: v
        for k, v in dotenv_values(local_env).items()
        if v is not None and not (k in NUMBERS and not v.strip())
    }
    env = {
        "QLOO_API_KEY": qloo_key(qloo_config),
        "QLOO_BASE_URL": QLOO_BASE,
        "QLOO_TRUSTED_BASE_URL": QLOO_BASE,
        **{k: v for k, v in local.items() if k.startswith("AGENT_") or k in SHARED},
        "ALLOW_LIVE_QLOO": "true",
        # Caddy reaches the app from this Docker network; trust its forwarded client
        # address from Caddy alone, or from the network (deploy/README.md says when).
        "FORWARDED_ALLOW_IPS": trusted.get("PROXY_ADDRESS", subnet),
        "PROXY_NETWORK": network,
        **trusted,
    }
    # Anthropic's own API needs no base URL (decision 25).
    required = [
        k for k in REQUIRED if not (k == "AGENT_BASE_URL" and env.get("AGENT_API") == "anthropic")
    ]
    bad = [k for k in NUMBERS if k in env and not (env[k].strip().isdigit() and int(env[k]) > 0)]
    if bad:
        raise MissingValue("not a whole number above zero: " + ", ".join(bad))
    missing = [k for k in required if not env.get(k, "").strip()]
    if missing:
        raise MissingValue("missing or empty: " + ", ".join(missing))
    return env


def render(env: dict[str, str]) -> str:
    # Docker's env_file takes each line literally: no quotes, no comments.
    bad = [k for k, v in env.items() if "\n" in v]
    if bad:
        raise MissingValue("values with a line break: " + ", ".join(bad))
    return "".join(f"{k}={v}\n" for k, v in env.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subnet", required=True, help="the network's subnets, space-separated")
    parser.add_argument("--network", required=True)
    parser.add_argument("--address", default="", help="the proxy's fixed IPv4 address, if any")
    parser.add_argument("--members", default="", help="the network's containers (see proxy_holder)")
    parser.add_argument("--local-env", type=Path, default=Path(".env"))
    parser.add_argument("--qloo-config", type=Path, default=Path.home() / ".qloo" / "config")
    args = parser.parse_args()
    address = args.address.strip()
    try:
        text = render(
            build_env(args.local_env, args.qloo_config, args.subnet, args.network, address)
        )
        holder = proxy_holder(args.members, address) if address else ""
    except MissingValue as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    if holder:
        print(
            f"→ Trusting forwarded client addresses from {holder} ({address}) only", file=sys.stderr
        )
    else:
        print(f"⚠ No PROXY_ADDRESS: trusting every container on {args.network}", file=sys.stderr)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
