"""Tests for the Modbus TCP side channel.

The device's Modbus server serves one session and locks up under frequent
access, so the properties worth testing are not "does it write" but "does it
refuse to touch the device when it should not": connections are always closed,
unchanged values never open one at all, and the rate limit rejects rather than
queues.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.marstek_ha.const import (
    MODBUS_REG_MAX_CHARGE_POWER,
    MODBUS_REG_MAX_DISCHARGE_POWER,
)
from custom_components.marstek_ha.modbus import (
    MarstekModbusError,
    MarstekModbusRateLimited,
    MarstekModbusWriter,
)


class _FakeClient:
    """Stands in for pymodbus's AsyncModbusTcpClient."""

    def __init__(self, *, connect_ok=True, error=False, registers=(1200, 2500)):
        self._connect_ok = connect_ok
        self._error = error
        self._registers = list(registers)
        self.closed = 0
        self.writes: list[tuple[int, int]] = []
        self.reads: list[tuple[int, int]] = []

    async def connect(self):
        return self._connect_ok

    def close(self):
        self.closed += 1

    def _response(self, registers=None):
        response = MagicMock()
        response.isError.return_value = self._error
        response.registers = registers if registers is not None else []
        return response

    async def read_holding_registers(self, address, *, count=1, device_id=1):
        self.reads.append((address, count))
        return self._response(self._registers[:count])

    async def write_register(self, address, value, *, device_id=1):
        self.writes.append((address, value))
        if not self._error:
            self._registers = list(self._registers)
        return self._response()


def _patch_client(client):
    """Patch the lazily imported pymodbus client with a fake."""
    module = MagicMock()
    module.AsyncModbusTcpClient = MagicMock(return_value=client)
    return patch.dict("sys.modules", {"pymodbus": MagicMock(), "pymodbus.client": module})


def _writer(**kwargs):
    kwargs.setdefault("min_interval", 0)
    return MarstekModbusWriter("192.0.2.10", 502, 1, **kwargs)


async def test_read_limits_returns_both_registers_in_one_transaction():
    """Both limits are adjacent, so one read must cover them."""
    client = _FakeClient(registers=(800, 2500))
    writer = _writer()

    with _patch_client(client):
        values = await writer.async_read_limits()

    assert values == {
        MODBUS_REG_MAX_CHARGE_POWER: 800,
        MODBUS_REG_MAX_DISCHARGE_POWER: 2500,
    }
    assert client.reads == [(MODBUS_REG_MAX_CHARGE_POWER, 2)]
    assert client.closed == 1


async def test_read_failure_does_not_raise():
    """A device that refuses the startup read must not block the entry load."""
    client = _FakeClient(connect_ok=False)
    writer = _writer()

    with _patch_client(client):
        assert await writer.async_read_limits() == {}

    # Still closed, even though connect() reported failure.
    assert client.closed == 1


async def test_write_sends_value_and_closes():
    client = _FakeClient()
    writer = _writer()

    with _patch_client(client):
        await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 0)

    assert client.writes == [(MODBUS_REG_MAX_CHARGE_POWER, 0)]
    assert client.closed == 1
    assert writer.known_value(MODBUS_REG_MAX_CHARGE_POWER) == 0


async def test_unchanged_value_opens_no_connection():
    """The cheapest protection: an unchanged limit must not touch the device."""
    client = _FakeClient()
    writer = _writer()

    with _patch_client(client):
        await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 0)
        await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 0)

    assert client.writes == [(MODBUS_REG_MAX_CHARGE_POWER, 0)]
    assert client.closed == 1


async def test_rate_limit_rejects_rather_than_queues():
    """A too-soon write is dropped, so no backlog can build up."""
    client = _FakeClient()
    writer = _writer(min_interval=60)

    with _patch_client(client):
        await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 0)
        with pytest.raises(MarstekModbusRateLimited):
            await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 2500)

    # Only the first write reached the device.
    assert client.writes == [(MODBUS_REG_MAX_CHARGE_POWER, 0)]
    assert writer.known_value(MODBUS_REG_MAX_CHARGE_POWER) == 0


async def test_rejected_write_forgets_the_cached_value():
    """After a failure the register's content is unknown, so the next write must go out."""
    client = _FakeClient(error=True)
    writer = _writer()

    with _patch_client(client):
        with pytest.raises(MarstekModbusError):
            await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 500)

    assert writer.known_value(MODBUS_REG_MAX_CHARGE_POWER) is None
    assert client.closed == 1


async def test_out_of_range_value_is_refused_before_connecting():
    client = _FakeClient()
    writer = _writer()

    with _patch_client(client):
        with pytest.raises(MarstekModbusError):
            await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 5000)

    assert client.writes == []
    assert client.closed == 0


async def test_connection_is_closed_even_when_the_transaction_raises():
    """The device has one session; leaking it is the worst possible failure."""
    client = _FakeClient()
    client.write_register = AsyncMock(side_effect=OSError("boom"))
    writer = _writer()

    with _patch_client(client):
        with pytest.raises(MarstekModbusError):
            await writer.async_write_limit(MODBUS_REG_MAX_CHARGE_POWER, 100)

    assert client.closed == 1
