"""Tests for the binary sensor debounce.

The behaviour under test is that a flag holds its value through isolated
deviating readings -- the CT Connected sensor produced 135 spurious 0-readings
in twelve hours on real hardware, nearly all of them one poll long.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.marstek_ha.binary_sensor import (
    BINARY_SENSOR_TYPES,
    MarstekBinarySensor,
)
from custom_components.marstek_ha.const import BINARY_FLAG_DEBOUNCE, DATA_EM_STATUS

CT_DESCRIPTION = next(d for d in BINARY_SENSOR_TYPES if d.key == "ct_connected")


def _sensor():
    """Build a CT sensor around a stub coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "aabbcc"
    coordinator.data = {}
    coordinator.config_entry.title = "Marstek"

    sensor = MarstekBinarySensor(coordinator, CT_DESCRIPTION)
    return sensor, coordinator


def _poll(sensor, coordinator, ct_state):
    """Feed one poll result through the filter."""
    coordinator.data = (
        {} if ct_state is None else {DATA_EM_STATUS: {"ct_state": ct_state}}
    )
    sensor._advance()
    return sensor.is_on


def test_first_reading_is_published_immediately():
    sensor, coordinator = _sensor()
    assert sensor.is_on is None
    assert _poll(sensor, coordinator, 1) is True


def test_single_deviating_reading_is_ignored():
    """One poll reporting 0 must not flip the sensor -- the actual bug."""
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    assert _poll(sensor, coordinator, 0) is True
    assert _poll(sensor, coordinator, 1) is True


def test_sustained_change_is_published():
    """A CT that really is gone must still be reported."""
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    for _ in range(BINARY_FLAG_DEBOUNCE - 1):
        assert _poll(sensor, coordinator, 0) is True
    assert _poll(sensor, coordinator, 0) is False


def test_an_interrupted_run_restarts_the_count():
    """Two isolated blips must not add up to a change."""
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    for _ in range(BINARY_FLAG_DEBOUNCE - 1):
        _poll(sensor, coordinator, 0)
    # One agreeing reading clears the pending change entirely.
    assert _poll(sensor, coordinator, 1) is True
    for _ in range(BINARY_FLAG_DEBOUNCE - 1):
        assert _poll(sensor, coordinator, 0) is True


def test_missing_reading_holds_the_last_value_without_counting():
    """"No answer" is not "CT lost", and it must not advance a pending change."""
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    for _ in range(BINARY_FLAG_DEBOUNCE * 2):
        assert _poll(sensor, coordinator, None) is True


def test_gaps_do_not_shorten_a_genuine_change():
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    _poll(sensor, coordinator, 0)
    assert _poll(sensor, coordinator, None) is True
    for _ in range(BINARY_FLAG_DEBOUNCE - 2):
        assert _poll(sensor, coordinator, 0) is True
    assert _poll(sensor, coordinator, 0) is False


def test_reading_the_property_repeatedly_does_not_advance_the_filter():
    """HA may read is_on several times per state write; that must not count."""
    sensor, coordinator = _sensor()
    _poll(sensor, coordinator, 1)

    coordinator.data = {DATA_EM_STATUS: {"ct_state": 0}}
    sensor._advance()
    for _ in range(BINARY_FLAG_DEBOUNCE * 3):
        assert sensor.is_on is True
