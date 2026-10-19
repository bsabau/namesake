import pytest

from app.animals import Roster, load_roster
from app.config import get_settings


@pytest.fixture(scope="session")
def roster() -> Roster:
    return load_roster(get_settings().animals_file)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """No test reaches Qloo, a model, the classifier, the geocoder, or the real cache.

    The cache and recordings point at an empty temp folder, live Qloo calls are
    off, no model, classifier or geocoder is configured, so any run falls back to the
    template.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "cache_db", tmp_path / "cache.sqlite")
    monkeypatch.setattr(settings, "qloo_recordings", tmp_path / "recordings")
    monkeypatch.setattr(settings, "allow_live_qloo", False)
    monkeypatch.setattr(settings, "agent_base_url", None)
    monkeypatch.setattr(settings, "agent_api_key", None)
    monkeypatch.setattr(settings, "agent_model", None)
    # The fallbacks too: a key in a local .env would otherwise reach a real model.
    # A fresh allowance for adding animals, so one test's additions never count in another.
    from app import main
    from app.places import Allowance

    monkeypatch.setattr(main, "ADD_ALLOWANCE", Allowance(per_minute=5))
    for name in type(settings).model_fields:
        if name.startswith("agent_fallback_") and name.endswith(("_api_key", "_model")):
            monkeypatch.setattr(settings, name, None)
    monkeypatch.setattr(settings, "geocoder_url", "")
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    return settings
