import pytest

from app.animals import Roster, load_roster
from app.config import get_settings


@pytest.fixture(scope="session")
def roster() -> Roster:
    return load_roster(get_settings().animals_file)
