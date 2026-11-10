"""deploy/make_env.py: the server's .env, built from local config without printing a value.

Synthetic files only; no real key is read.
"""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "make_env", Path(__file__).parent.parent / "deploy" / "make_env.py"
)
make_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_env)

LOCAL = """\
# a comment
AGENT_BASE_URL=https://example.invalid/v1
AGENT_API_KEY="fake-agent-key"   # trailing comment
AGENT_MODEL=example-model
AGENT_API=responses
OTHER=ignored
"""


def files(tmp_path, local=LOCAL, qloo="api_key = fake-qloo-key\nbase_url = https://x\n"):
    (tmp_path / ".env").write_text(local)
    (tmp_path / "config").write_text(qloo)
    return tmp_path / ".env", tmp_path / "config"


MEMBERS = """\
proxy-caddy-1 172.30.0.2/24 true 80/tcp,443/tcp,443/udp,
mexicoproj-app-1 172.30.0.129/24 true
namesake-app-1 172.30.0.130/24 true
"""


def test_quotes_and_comments_are_not_baked_into_values(tmp_path):
    env = make_env.build_env(*files(tmp_path), "172.18.0.0/16", "proxy_default")
    assert env["AGENT_API_KEY"] == "fake-agent-key"
    assert env["QLOO_API_KEY"] == "fake-qloo-key"
    assert env["FORWARDED_ALLOW_IPS"] == "172.18.0.0/16" and "OTHER" not in env
    text = make_env.render(env)
    assert "AGENT_API_KEY=fake-agent-key\n" in text and '"' not in text and "#" not in text


def test_a_missing_value_names_the_variable_and_never_a_value(tmp_path):
    local, qloo = files(tmp_path, local=LOCAL.replace("AGENT_MODEL=example-model\n", ""))
    with pytest.raises(make_env.MissingValue) as err:
        make_env.build_env(local, qloo, "10.0.0.0/8", "n")
    assert "AGENT_MODEL" in str(err.value) and "fake" not in str(err.value)

    local, qloo = files(tmp_path, qloo="base_url = https://x\n")
    with pytest.raises(make_env.MissingValue, match="no api_key"):
        make_env.build_env(local, qloo, "10.0.0.0/8", "n")
    with pytest.raises(make_env.MissingValue, match="not found"):
        make_env.build_env(local, tmp_path / "nope", "10.0.0.0/8", "n")


def test_the_script_prints_nothing_on_failure(tmp_path, capsys, monkeypatch):
    local, _ = files(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["make_env.py", "--subnet", "10.0.0.0/8", "--network", "n", "--local-env", str(local),
         "--qloo-config", str(tmp_path / "missing")],
    )  # fmt: skip
    assert make_env.main() == 1
    out, err = capsys.readouterr()
    assert out == "" and "QLOO_API_KEY" in err and "fake" not in err


def test_only_a_valid_ipv4_proxy_subnet_is_trusted():
    # DeepSeek, Flash, Grok: a dual-stack network glued its subnets into one bad value.
    assert make_env.proxy_subnet("172.18.0.0/16 fd00::/64 ") == "172.18.0.0/16"
    assert make_env.proxy_subnet("fd00::/64 10.0.0.0/8") == "10.0.0.0/8"
    with pytest.raises(make_env.MissingValue, match="no IPv4 subnet"):
        make_env.proxy_subnet("172.18.0.0/16fd00::/64")


def test_the_geocoder_setting_goes_to_the_host_even_when_empty(tmp_path):
    # Flash: GEOCODER_URL= in the local .env never reached the host, so lookups stayed on.
    env = make_env.build_env(
        *files(tmp_path, LOCAL + "GEOCODER_URL=\n"), "172.18.0.0/16", "proxy_default"
    )
    assert env["GEOCODER_URL"] == "" and "GEOCODER_URL=\n" in make_env.render(env)


def test_the_map_tiles_key_goes_to_the_host_and_is_optional(tmp_path):
    env = make_env.build_env(
        *files(tmp_path, LOCAL + "MAP_TILES_KEY=fake-tiles-key\n"), "172.18.0.0/16", "proxy_default"
    )
    assert env["MAP_TILES_KEY"] == "fake-tiles-key"
    env = make_env.build_env(*files(tmp_path), "172.18.0.0/16", "proxy_default")
    assert "MAP_TILES_KEY" not in env


def test_fallbacks_pass_through_and_an_anthropic_main_needs_no_base_url(tmp_path):
    local = LOCAL + "AGENT_FALLBACK_1_API_KEY=fake-fallback-key\nAGENT_FALLBACK_1_API=anthropic\n"
    env = make_env.build_env(*files(tmp_path, local=local), "172.18.0.0/16", "n")
    assert env["AGENT_FALLBACK_1_API_KEY"] == "fake-fallback-key"
    anthropic_main = LOCAL.replace("AGENT_BASE_URL=https://example.invalid/v1\n", "").replace(
        "AGENT_API=responses", "AGENT_API=anthropic"
    )
    env = make_env.build_env(*files(tmp_path, local=anthropic_main), "172.18.0.0/16", "n")
    assert "AGENT_BASE_URL" not in env


def test_the_limits_on_live_work_go_to_the_host_when_set(tmp_path):
    env = make_env.build_env(*files(tmp_path), "172.18.0.0/16", "proxy_default")
    assert "LIVE_RUNS_PER_DAY" not in env
    local = (
        LOCAL + "LIVE_RUNS_PER_DAY=90\nLIVE_RUNS_PER_VISITOR_PER_HOUR=8\nNEW_LOCATIONS_PER_DAY=12\n"
    )
    env = make_env.build_env(*files(tmp_path, local), "172.18.0.0/16", "proxy_default")
    assert env["LIVE_RUNS_PER_DAY"] == "90" and env["LIVE_RUNS_PER_VISITOR_PER_HOUR"] == "8"
    assert env["NEW_LOCATIONS_PER_DAY"] == "12"
    # muse: an empty cap would stop the app from starting; the host keeps its default.
    env = make_env.build_env(
        *files(tmp_path, LOCAL + "LIVE_RUNS_PER_DAY=\n"), "172.18.0.0/16", "proxy_default"
    )
    assert "LIVE_RUNS_PER_DAY" not in env


def test_a_cap_that_is_not_a_positive_number_stops_the_deploy(tmp_path):
    # Flash: text would stop the app starting, and 0 would switch live runs off.
    for value in ("abc", "0", "-3", "1.5"):
        local, qloo = files(tmp_path, LOCAL + f"LIVE_RUNS_PER_DAY={value}\n")
        with pytest.raises(make_env.MissingValue, match="LIVE_RUNS_PER_DAY") as err:
            make_env.build_env(local, qloo, "172.18.0.0/16", "proxy_default")
        assert value not in str(err.value).replace("LIVE_RUNS_PER_DAY", "")


def test_a_fixed_proxy_address_is_the_only_one_trusted(tmp_path):
    # host-proxy gives Caddy 172.30.0.2, so other apps on its network cannot forge a visitor.
    env = make_env.build_env(
        *files(tmp_path), "172.30.0.0/24 fd00::/64", "proxy", " 172.30.0.2 ", MEMBERS
    )
    assert env["FORWARDED_ALLOW_IPS"] == "172.30.0.2" and env["PROXY_ADDRESS"] == "172.30.0.2"
    assert "PROXY_ADDRESS=172.30.0.2\n" in make_env.render(env)
    # Without one, the whole subnet is trusted and no PROXY_ADDRESS is written.
    env = make_env.build_env(*files(tmp_path), "172.18.0.0/16", "proxy_default", "")
    assert env["FORWARDED_ALLOW_IPS"] == "172.18.0.0/16" and "PROXY_ADDRESS" not in env


@pytest.mark.parametrize("address", ["172.31.0.2", "fd00::2", "caddy", "172.30.0.0/24"])
def test_a_proxy_address_off_the_network_stops_the_deploy(tmp_path, address):
    with pytest.raises(make_env.MissingValue, match="PROXY_ADDRESS"):
        make_env.build_env(*files(tmp_path), "172.30.0.0/24", "proxy", address, MEMBERS)


def test_only_the_running_proxy_publishing_https_is_trusted(tmp_path):
    # Flash: a mistyped PROXY_ADDRESS on SOSPI's app passed the first check and was trusted.
    assert make_env.proxy_holder(MEMBERS, "172.30.0.2") == "proxy-caddy-1"
    for app in ("172.30.0.129", "172.30.0.130"):
        with pytest.raises(make_env.MissingValue, match="publishes no HTTPS port"):
            make_env.proxy_holder(MEMBERS, app)
    with pytest.raises(make_env.MissingValue, match="no container .* holds 172.30.0.13$"):
        make_env.proxy_holder(MEMBERS, "172.30.0.13")  # a prefix of .130, never a match
    stopped = MEMBERS.replace("172.30.0.2/24 true", "172.30.0.2/24 false")
    with pytest.raises(make_env.MissingValue, match="not running, or is gone"):
        make_env.proxy_holder(stopped, "172.30.0.2")
    with pytest.raises(make_env.MissingValue, match="no container"):
        make_env.proxy_holder("", "172.30.0.2")
    # build_env refuses an address without the proxy behind it, so no caller skips the check.
    with pytest.raises(make_env.MissingValue, match="no container"):
        make_env.build_env(*files(tmp_path), "172.30.0.0/24", "proxy", "172.30.0.2")


def test_the_script_says_whom_it_trusts(tmp_path, capsys, monkeypatch):
    local, qloo = files(tmp_path)
    base = ["make_env.py", "--subnet", "172.30.0.0/24", "--network", "proxy",
            "--local-env", str(local), "--qloo-config", str(qloo)]  # fmt: skip
    monkeypatch.setattr("sys.argv", [*base, "--address", "172.30.0.2", "--members", MEMBERS])
    assert make_env.main() == 0
    out, err = capsys.readouterr()
    assert (
        "FORWARDED_ALLOW_IPS=172.30.0.2\n" in out and "from proxy-caddy-1 (172.30.0.2) only" in err
    )
    monkeypatch.setattr("sys.argv", [*base, "--address", "172.30.0.129", "--members", MEMBERS])
    assert make_env.main() == 1
    out, err = capsys.readouterr()
    assert out == "" and "mexicoproj-app-1" in err
    monkeypatch.setattr("sys.argv", base)
    assert make_env.main() == 0
    out, err = capsys.readouterr()
    assert (
        "FORWARDED_ALLOW_IPS=172.30.0.0/24\n" in out and "trusting every container on proxy" in err
    )
