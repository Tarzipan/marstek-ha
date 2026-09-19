"""Tests for the value functions that reinterpret raw device fields.

These are pure functions over one poll's payload, so they are tested directly
rather than through Home Assistant.
"""
from __future__ import annotations

import pytest

from custom_components.marstek_ha.const import DATA_BATTERY, DATA_DEVICE
from custom_components.marstek_ha.sensor import _battery_temperature


def _payload(bat_temp, firmware=150):
    return {
        DATA_BATTERY: {"bat_temp": bat_temp},
        DATA_DEVICE: {"ver": firmware},
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Whole degrees, as reported by both a build-144 and a build-150 unit.
        (27, 27.0),
        (18, 18.0),
        (0, 0.0),
        (-5, -5.0),
        # Tenths of a degree, as reported by other units.
        (340, 34.0),
        (250, 25.0),
        (105, 10.5),
    ],
)
def test_temperature_scaling_is_detected_from_magnitude(raw, expected):
    assert _battery_temperature(_payload(raw)) == pytest.approx(expected)


def test_temperature_scaling_ignores_the_firmware_version():
    """Firmware build does not decide the scaling -- measurement disproved that.

    A build-144 unit and a build-150 unit both report whole degrees, so the same
    raw value must come out the same way regardless of what `ver` says.
    """
    assert _battery_temperature(_payload(27, firmware=144)) == 27.0
    assert _battery_temperature(_payload(27, firmware=150)) == 27.0
    assert _battery_temperature(_payload(340, firmware=144)) == 34.0
    assert _battery_temperature(_payload(340, firmware=150)) == 34.0


def test_temperature_survives_a_missing_or_unusable_reading():
    assert _battery_temperature({DATA_BATTERY: {}}) is None
    assert _battery_temperature({}) is None
    assert _battery_temperature(_payload("n/a")) is None
