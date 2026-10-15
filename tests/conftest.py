import pytest

from app.animals import Roster, load_roster
from app.config import get_settings


@pytest.fixture(scope="session")
def roster() -> Roster:
    return load_roster(get_settings().animals_file)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """No test reaches Qloo, a model, or the real cache in var/.

    The cache and recordings point at an empty temp folder, live Qloo calls are
    off, and no model is configured, so any run falls back to the template.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_db", tmp_path / "cache.sqlite")
    monkeypatch.setattr(settings, "qloo_recordings", tmp_path / "recordings")
    monkeypatch.setattr(settings, "allow_live_qloo", False)
    monkeypatch.setattr(settings, "agent_base_url", None)
    monkeypatch.setattr(settings, "agent_api_key", None)
    monkeypatch.setattr(settings, "agent_model", None)
    return settings
