"""Settings read from the environment (and `.env` in development).

Secrets are `SecretStr` so they never show up in a repr or a log line.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Qloo harness. On the dev machine these come from ~/.qloo/config instead,
    # so all three are optional here.
    qloo_api_key: SecretStr | None = None
    qloo_base_url: str | None = None
    qloo_trusted_base_url: str | None = None
    # Seconds between live Qloo calls, across processes. The key is rate-limited.
    qloo_min_interval: float = 5.0

    # The agent's model. Configuration, never code.
    agent_base_url: str | None = None
    agent_api_key: SecretStr | None = None
    agent_model: str | None = None
    agent_api: str = "chat"

    # Default interface: a folder under app/ui/. `?ui=<name>` overrides it per request.
    ui: str = "classic"

    animals_file: Path = ROOT / "data" / "animals" / "animals.json"
    locations_file: Path = ROOT / "data" / "locations.json"
    seeds_file: Path = ROOT / "data" / "seeds.json"
    # Real Qloo data: git-ignored, never committed, deployed privately.
    cache_db: Path = ROOT / "var" / "cache.sqlite"
    qloo_recordings: Path = ROOT / "var" / "qloo-recordings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
