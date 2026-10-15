"""Run harness workflows through `qloo exec`, with a cache and replayable recordings.

Live calls are spaced at least `min_interval` seconds apart, measured from the
last live call recorded in the cache database, so separate processes share it.

Lookup order for every call: the SQLite cache, then the recordings folder, then
(in live mode only) the harness itself. Live results that are not errors are
written to both, so a later run can replay them without spending quota.
"""

import json
import os
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.config import Settings
from app.qloo.cache import Cache, cache_key
from app.qloo.envelope import Envelope

Mode = Literal["live", "replay"]
Runner = Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]]

# What a `qloo exec` exit code means when stdout carries no envelope.
EXIT_MEANING = {1: "harness failure", 2: "invalid input", 4: "missing Qloo credentials"}


class QlooExecError(RuntimeError):
    """The harness failed without producing an envelope."""


class ReplayMiss(LookupError):
    """Replay mode was asked for a call that was never recorded."""


def harness_env(settings: Settings) -> dict[str, str]:
    """The parent environment plus any Qloo settings from `.env`, for the child process."""
    env = dict(os.environ)
    if settings.qloo_api_key is not None:
        env["QLOO_API_KEY"] = settings.qloo_api_key.get_secret_value()
    if settings.qloo_base_url:
        env["QLOO_BASE_URL"] = settings.qloo_base_url
    if settings.qloo_trusted_base_url:
        env["QLOO_TRUSTED_BASE_URL"] = settings.qloo_trusted_base_url
    return env


def _subprocess_runner(
    args: list[str], env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)


class QlooClient:
    def __init__(
        self,
        cache: Cache,
        *,
        mode: Mode = "live",
        recordings: Path | None = None,
        env: dict[str, str] | None = None,
        runner: Runner = _subprocess_runner,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        min_interval: float = 5.0,
        retry_delay: float = 5.0,
        timeout: float = 90.0,
    ):
        self.cache = cache
        self.mode = mode
        self.recordings = recordings
        self.env = env if env is not None else dict(os.environ)
        self.runner = runner
        self.sleep = sleep
        self.clock = clock
        self.min_interval = min_interval
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.live_calls = 0

    def run(self, operation: str, input_: dict[str, Any]) -> Envelope:
        cached = self.cache.get(operation, input_)
        if cached is not None:
            return Envelope.parse(cached)

        recorded = self._read_recording(operation, input_)
        if recorded is not None:
            self.cache.put(operation, input_, recorded)
            return Envelope.parse(recorded)

        if self.mode == "replay":
            raise ReplayMiss(f"no recording for {operation} {cache_key(operation, input_)[:16]}")

        data = self._call(operation, input_)
        envelope = Envelope.parse(data)
        if envelope.retryable:
            # The harness's recovery text says to retry the same request once.
            self.sleep(self.retry_delay)
            data = self._call(operation, input_)
            envelope = Envelope.parse(data)

        if envelope.status != "error":
            self.cache.put(operation, input_, data)
            self._write_recording(operation, input_, data)
        return envelope

    def _call(self, operation: str, input_: dict[str, Any]) -> dict[str, Any]:
        args = ["qloo", "exec", operation, "--input", json.dumps(input_)]
        self._space_out()
        self.live_calls += 1
        try:
            proc = self.runner(args, self.env, self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise QlooExecError(f"qloo exec {operation} timed out after {self.timeout}s") from exc
        except OSError as exc:
            raise QlooExecError(f"could not start the qloo harness: {exc}") from exc

        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = None
        if isinstance(data, dict) and ("status" in data or "error" in data):
            return data
        meaning = EXIT_MEANING.get(proc.returncode, "unexpected output")
        raise QlooExecError(f"qloo exec {operation} exited {proc.returncode} ({meaning})")

    def _space_out(self) -> None:
        """Wait until `min_interval` seconds have passed since the last live call."""
        last = self.cache.last_live_call()
        if last is not None:
            wait = last + self.min_interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.cache.mark_live_call(self.clock())

    def _recording_path(self, operation: str, input_: dict[str, Any]) -> Path | None:
        if self.recordings is None:
            return None
        return self.recordings / f"{operation}__{cache_key(operation, input_)[:16]}.json"

    def _read_recording(self, operation: str, input_: dict[str, Any]) -> dict[str, Any] | None:
        path = self._recording_path(operation, input_)
        if path is None or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["envelope"]

    def _write_recording(
        self, operation: str, input_: dict[str, Any], envelope: dict[str, Any]
    ) -> None:
        path = self._recording_path(operation, input_)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "operation": operation,
            "input": input_,
            "recorded_at": datetime.now(UTC).isoformat(),
            "envelope": envelope,
        }
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
