"""The exec wrapper, driven by a fake runner: no test reaches the real harness."""

import json
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.qloo.cache import Cache
from app.qloo.exec import QlooClient, QlooExecError, ReplayMiss, harness_env

SYNTHETIC = Path(__file__).parent / "fixtures" / "qloo" / "synthetic"
INPUT = {"entity": "00000000-0000-4000-8000-000000000001", "within": "Example City"}


def fixture(name: str) -> str:
    return (SYNTHETIC / f"{name}.json").read_text(encoding="utf-8")


class FakeRunner:
    """Returns queued (stdout, exit code) pairs and records every call."""

    def __init__(self, *outputs: tuple[str, int]):
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, args, env, timeout):
        self.calls.append(args)
        self.envs.append(env)
        stdout, code = self.outputs.pop(0)
        return subprocess.CompletedProcess(args, code, stdout=stdout, stderr="")


@pytest.fixture
def cache(tmp_path) -> Cache:
    return Cache(tmp_path / "cache.sqlite")


def client(cache, runner, **kwargs) -> QlooClient:
    kwargs.setdefault("min_interval", 0)
    return QlooClient(cache, runner=runner, sleep=lambda _: None, env={}, **kwargs)


def test_live_call_sends_the_input_and_caches_the_result(cache):
    runner = FakeRunner((fixture("where_popular__ok"), 0))
    qloo = client(cache, runner)
    env = qloo.run("where_popular", INPUT)
    assert env.status == "ok"
    assert runner.calls == [["qloo", "exec", "where_popular", "--input", json.dumps(INPUT)]]
    # Same input again: served from the cache, no second call.
    assert qloo.run("where_popular", dict(reversed(INPUT.items()))).status == "ok"
    assert qloo.live_calls == 1


def test_needs_input_is_returned_and_cached_not_forced(cache):
    runner = FakeRunner((fixture("where_popular__needs_input"), 0))
    qloo = client(cache, runner)
    env = qloo.run("where_popular", {"entity": "Example Name", "within": "Example City"})
    assert env.status == "needs_input" and len(env.candidates) == 2
    assert cache.get("where_popular", {"entity": "Example Name", "within": "Example City"})


def test_retryable_error_is_retried_once(cache):
    runner = FakeRunner((fixture("error__retryable"), 1), (fixture("where_popular__ok"), 0))
    slept = []
    qloo = QlooClient(
        cache, runner=runner, sleep=slept.append, retry_delay=3, min_interval=0, env={}
    )
    assert qloo.run("where_popular", INPUT).status == "ok"
    assert len(runner.calls) == 2 and slept == [3]


def test_retryable_error_twice_is_returned_and_not_cached(cache):
    runner = FakeRunner((fixture("error__retryable"), 1), (fixture("error__retryable"), 1))
    qloo = client(cache, runner)
    env = qloo.run("where_popular", INPUT)
    assert env.status == "error" and env.retryable
    assert len(runner.calls) == 2
    assert cache.get("where_popular", INPUT) is None


@pytest.mark.parametrize(("name", "code"), [("error__not_retryable", 1), ("error__tool_input", 2)])
def test_non_retryable_error_is_not_retried(cache, name, code):
    runner = FakeRunner((fixture(name), code))
    qloo = client(cache, runner)
    assert qloo.run("where_popular", INPUT).status == "error"
    assert len(runner.calls) == 1
    assert cache.get("where_popular", INPUT) is None


@pytest.mark.parametrize(("code", "meaning"), [(4, "missing Qloo credentials"), (1, "failure")])
def test_exit_without_an_envelope_raises(cache, code, meaning):
    qloo = client(cache, FakeRunner(("not json", code)))
    with pytest.raises(QlooExecError, match=meaning):
        qloo.run("where_popular", INPUT)


def test_timeout_and_missing_binary_raise(cache):
    def timeout_runner(args, env, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    def missing_runner(args, env, timeout):
        raise FileNotFoundError("qloo")

    with pytest.raises(QlooExecError, match="timed out"):
        client(cache, timeout_runner).run("where_popular", INPUT)
    with pytest.raises(QlooExecError, match="could not start"):
        client(cache, missing_runner).run("where_popular", INPUT)


class FakeClock:
    def __init__(self, now: float):
        self.now = now
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_live_calls_are_spaced_out_across_clients(cache):
    clock = FakeClock(1000.0)
    ok = fixture("where_popular__ok")

    def spaced(runner):
        return QlooClient(
            cache, runner=runner, sleep=clock.sleep, clock=clock.time, min_interval=5, env={}
        )

    spaced(FakeRunner((ok, 0))).run("where_popular", INPUT)
    assert clock.slept == []
    clock.now += 2
    # A second client (another process, in practice) shares the cache and waits the rest.
    spaced(FakeRunner((ok, 0))).run("where_popular", {**INPUT, "limit": 5})
    assert clock.slept == [3]
    clock.now += 60
    spaced(FakeRunner((ok, 0))).run("where_popular", {**INPUT, "limit": 6})
    assert clock.slept == [3]
    # A cache hit is not a live call and never waits.
    spaced(FakeRunner()).run("where_popular", INPUT)
    assert clock.slept == [3]


def test_live_results_are_recorded_and_replay_without_calls(tmp_path, cache):
    recordings = tmp_path / "recordings"
    live = client(cache, FakeRunner((fixture("where_popular__ok"), 0)), recordings=recordings)
    live.run("where_popular", INPUT)
    [record] = list(recordings.glob("where_popular__*.json"))
    assert json.loads(record.read_text())["input"] == INPUT

    # A fresh cache in replay mode finds it in the recordings; the runner is never used.
    fresh = Cache(tmp_path / "other.sqlite")
    replay = client(fresh, FakeRunner(), mode="replay", recordings=recordings)
    assert replay.run("where_popular", INPUT).status == "ok"
    assert replay.live_calls == 0
    assert fresh.get("where_popular", INPUT) is not None


def test_replay_miss_never_calls_the_harness(tmp_path, cache):
    runner = FakeRunner()
    qloo = client(cache, runner, mode="replay", recordings=tmp_path)
    with pytest.raises(ReplayMiss):
        qloo.run("where_popular", INPUT)
    assert runner.calls == []


def test_harness_env_passes_settings_through(monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    settings = Settings(
        _env_file=None,
        qloo_api_key="test-key",
        qloo_base_url="https://example.invalid",
        qloo_trusted_base_url="https://example.invalid",
    )
    env = harness_env(settings)
    assert env["PATH"] == "/bin"
    assert env["QLOO_API_KEY"] == "test-key"
    assert env["QLOO_BASE_URL"] == env["QLOO_TRUSTED_BASE_URL"] == "https://example.invalid"
