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
