import pytest

from app.qloo.envelope import HeatmapCell
from app.qloo.geohash import bounds, decode, haversine_km, nearest, within


def cell(latitude: float, longitude: float, geohash: str = "dr5rks") -> HeatmapCell:
    return HeatmapCell.model_validate(
        {
            "location": {"latitude": latitude, "longitude": longitude, "geohash": geohash},
            "query": {"affinity": 0.5, "popularity": 0.4},
        }
    )


def test_decode_matches_the_reference_cell():
    latitude, longitude = decode("ezs42")
    assert latitude == pytest.approx(42.605, abs=0.01)
    assert longitude == pytest.approx(-5.603, abs=0.01)


def test_decode_a_long_cell_is_precise():
    latitude, longitude = decode("u4pruydqqvj")
    assert latitude == pytest.approx(57.64911, abs=0.0001)
    assert longitude == pytest.approx(10.40744, abs=0.0001)


def test_bounds_contain_the_centre_and_are_about_a_kilometre():
    south, west, north, east = bounds("dr5rks")
    latitude, longitude = decode("dr5rks")
    assert south < latitude < north
    assert west < longitude < east
    assert haversine_km(south, west, south, east) < 1.5
    assert haversine_km(south, west, north, west) < 1.5


def test_upper_case_is_accepted():
    assert decode("EZS42") == decode("ezs42")
    assert bounds("DR5RKS") == bounds("dr5rks")


@pytest.mark.parametrize("bad", ["", "   ", "ezs4!", "ezs4a", "a", "ezs42 "])
def test_a_bad_geohash_is_rejected(bad):
    with pytest.raises(ValueError):
        decode(bad)


def test_haversine_matches_new_york_to_los_angeles():
    assert haversine_km(40.7128, -74.0060, 34.0522, -118.2437) == pytest.approx(3936, abs=5)


def test_haversine_of_the_same_point_is_zero():
    assert haversine_km(40.0, -73.0, 40.0, -73.0) == pytest.approx(0.0)


def test_nearest_picks_the_closest_cell():
    cells = [cell(40.7000, -73.9900), cell(40.7100, -74.0000), cell(40.9000, -73.9000)]
    found = nearest(cells, 40.7128, -74.0060)
    assert found is not None
    assert found.location.latitude == 40.7100


def test_nearest_of_nothing_is_none():
    assert nearest([], 40.7128, -74.0060) is None


def test_within_keeps_only_near_cells_nearest_first():
    close = cell(40.7120, -74.0060)
    farther = cell(40.7300, -74.0060)
    far = cell(40.9000, -74.0060)
    assert within([far, farther, close], 40.7128, -74.0060, 5.0) == [close, farther]


def test_within_of_nothing_is_empty():
    assert within([], 40.7128, -74.0060, 5.0) == []
