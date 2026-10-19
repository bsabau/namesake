"""Build the server's .env from this machine's config, for `deploy/deploy.sh --env`.

Prints the file to stdout, which deploy.sh pipes straight to the server; it never
prints a value anywhere else. A missing or empty value stops it with the variable's
name only, before anything is sent.

    uv run python deploy/make_env.py --subnet 172.18.0.0/16 --network proxy_default
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
SHARED = (
    "GEOCODER_URL",
    "QLOO_MIN_INTERVAL",
    "TYPESAFE_API_KEY",
    "TYPESAFE_MODEL",
    "TYPESAFE_BASE_URL",
    "MAP_TILES_KEY",
)
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


def build_env(local_env: Path, qloo_config: Path, subnet: str, network: str) -> dict[str, str]:
    subnet = proxy_subnet(subnet)
    local = {k: v for k, v in dotenv_values(local_env).items() if v is not None}
    env = {
        "QLOO_API_KEY": qloo_key(qloo_config),
        "QLOO_BASE_URL": QLOO_BASE,
        "QLOO_TRUSTED_BASE_URL": QLOO_BASE,
        **{k: v for k, v in local.items() if k.startswith("AGENT_") or k in SHARED},
        "ALLOW_LIVE_QLOO": "true",
        # Caddy reaches the app from this Docker network; trust its forwarded client
        # address from there (deploy/README.md says why the whole subnet).
        "FORWARDED_ALLOW_IPS": subnet,
        "PROXY_NETWORK": network,
    }
    # Anthropic's own API needs no base URL (decision 25).
    required = [
        k for k in REQUIRED if not (k == "AGENT_BASE_URL" and env.get("AGENT_API") == "anthropic")
    ]
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
    parser.add_argument("--local-env", type=Path, default=Path(".env"))
    parser.add_argument("--qloo-config", type=Path, default=Path.home() / ".qloo" / "config")
    args = parser.parse_args()
    try:
        text = render(build_env(args.local_env, args.qloo_config, args.subnet, args.network))
    except MissingValue as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
