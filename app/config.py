"""Settings read from the environment (and `.env` in development).

Secrets are `SecretStr` so they never show up in a repr or a log line.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Qloo harness. On the dev machine these come from ~/.qloo/config instead,
    # so all three are optional here.
    qloo_api_key: SecretStr | None = None
    qloo_base_url: str | None = None
    qloo_trusted_base_url: str | None = None
    # Seconds between live Qloo calls, across processes. The key is rate-limited: refused
    # after about 12 calls in 20 minutes on 15 October; 30 calls 10 s apart passed on
    # 17 October, but at 2 s `rank` was refused on 18 October (docs/decisions.md #20).
    # Qloo raised the hackathon limits on 21 October: 50 calls at 2 s and 1 s apart,
    # `rank` among them, all passed (docs/qloo-findings.md).
    qloo_min_interval: float = 2.0
    # Whether web runs may call Qloo live. Off, they use only the cache and recordings.
    allow_live_qloo: bool = True

    # The agent's model. Configuration, never code.
    agent_base_url: str | None = None
    agent_api_key: SecretStr | None = None
    agent_model: str | None = None
    agent_api: str = "chat"
    # How the model returns structured output: "native" (JSON schema), "prompted" or "tool".
    # The free development model only allows tool_choice "auto", so "tool" fails there.
    agent_output_mode: str = "native"
    # Up to two fallbacks, tried in order when a run cannot reach the model before them
    # (an error, a refused request, a timeout). Each takes the same five settings; "api"
    # may also be "anthropic" (Anthropic's own API; no base URL needed). Empty: none.
    agent_fallback_1_base_url: str | None = None
    agent_fallback_1_api_key: SecretStr | None = None
    agent_fallback_1_model: str | None = None
    agent_fallback_1_api: str = "chat"
    agent_fallback_1_output_mode: str = "native"
    agent_fallback_2_base_url: str | None = None
    agent_fallback_2_api_key: SecretStr | None = None
    agent_fallback_2_model: str | None = None
    agent_fallback_2_api: str = "chat"
    agent_fallback_2_output_mode: str = "native"

    @field_validator("agent_api", "agent_fallback_1_api", "agent_fallback_2_api", mode="before")
    @classmethod
    def _api_default(cls, value: str | None) -> str:
        """An empty `API=` line means the default, like a missing one, not a typo."""
        return value or "chat"

    @field_validator(
        "agent_output_mode",
        "agent_fallback_1_output_mode",
        "agent_fallback_2_output_mode",
        mode="before",
    )
    @classmethod
    def _output_mode_default(cls, value: str | None) -> str:
        return value or "native"

    # The classifier that sorts titles into pet-themed or not (app/classify.py). Without
    # a key it is off, and Namesake's AI judges the titles from their descriptions.
    typesafe_api_key: SecretStr | None = None
    typesafe_base_url: str = "https://api.typesafe.ai/v1"
    typesafe_model: str = "jev-latest"

    # Limits on live work (runs that call the model or Qloo, and new custom locations).
    # Saved results are free. Per visitor is per hour; the caps are per day (UTC).
    live_runs_per_visitor_per_hour: int = 6
    live_runs_per_day: int = 60
    new_locations_per_day: int = 10

    # Area names for the location field and the map pick (app/places.py). Empty turns the
    # suggestions and the map pick off; typing a place still works.
    geocoder_url: str = "https://photon.komoot.io"

    # Default interface: a folder under app/ui/. `?ui=<name>` overrides it per request.
    ui: str = "story"
    # CARTO basemap key for the story skin's maps (Positron in light mode, Dark Matter in
    # dark mode). Empty: OpenStreetMap's standard tiles. The one key that reaches the
    # browser, because tile requests come from the visitor's browser (AGENTS.md, Secrets):
    # a public basemap key, restricted by domain in CARTO's dashboard, never committed.
    # A SecretStr all the same, so it never shows in a settings dump; it is unwrapped
    # only where the tile URL is built (app/views/build.py, map_tiles).
    map_tiles_key: SecretStr | None = None

    animals_file: Path = ROOT / "data" / "animals" / "animals.json"
    locations_file: Path = ROOT / "data" / "locations.json"
    seeds_file: Path = ROOT / "data" / "seeds.json"
    # Real Qloo data: git-ignored, never committed, deployed privately.
    cache_db: Path = ROOT / "var" / "cache.sqlite"
    qloo_recordings: Path = ROOT / "var" / "qloo-recordings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
