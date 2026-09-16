"""Tests for the Marstek UDP transport.

These exercise marstek_api.py against a simulated device. The module
deliberately imports no Home Assistant code, so the protocol behaviour that
multi-device setups depend on can be verified in isolation.
"""
from __future__ import annotations

import asyncio
import json
import importlib
import sys
import types
from pathlib import Path

import pytest

# Load marstek_api without executing the package __init__, which pulls in Home
# Assistant. The API module itself depends only on the standard library.
_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "marstek_ha"
if "marstek_ha" not in sys.modules:
    _pkg = types.ModuleType("marstek_ha")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["marstek_ha"] = _pkg

marstek_api = importlib.import_module("marstek_ha.marstek_api")
MarstekAPI = marstek_api.MarstekAPI
MarstekDeviceError = marstek_api.MarstekDeviceError
MarstekTimeout = marstek_api.MarstekTimeout


class FakeDevice:
    """A UDP endpoint that answers Marstek requests like the real device."""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.requests: list[dict] = []
        # Highest number of requests the device was handling at once. The real
        # hardware serves one at a time and drops the rest.
        self.in_flight = 0
        self.max_in_flight = 0
        # Per-method behaviour: "ok", "drop", "error", or a delay in seconds.
        self.behaviour: dict[str, object] = {}
        self.results: dict[str, dict] = {}
        self.port = 0

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        device = self

        class _Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                device.transport = transport

            def datagram_received(self, data, addr):
                asyncio.create_task(device._respond(data, addr))

        transport, _ = await loop.create_datagram_endpoint(
            _Protocol, local_addr=("127.0.0.1", 0)
        )
        self.port = transport.get_extra_info("sockname")[1]

    async def _respond(self, data: bytes, addr) -> None:
        request = json.loads(data.decode())
        self.requests.append(request)
        method = request["method"]
        behaviour = self.behaviour.get(method, "ok")

        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await self._reply(request, method, behaviour, addr)
        finally:
            self.in_flight -= 1

    async def _reply(self, request: dict, method: str, behaviour, addr) -> None:
        if behaviour == "drop":
            return
        if isinstance(behaviour, (int, float)):
            await asyncio.sleep(behaviour)
        if behaviour == "error":
            payload = {"id": request["id"], "src": "fake", "error": {"code": -1}}
        else:
            payload = {
                "id": request["id"],
                "src": "fake",
                "result": self.results.get(method, {"method": method}),
            }
        if self.transport is not None:
            self.transport.sendto(json.dumps(payload).encode(), addr)

    def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()


@pytest.fixture
async def device(socket_enabled):
    """Provide a running fake device.

    Requests socket_enabled because these tests drive real loopback UDP, which
    the Home Assistant test harness blocks by default.
    """
    fake = FakeDevice()
    await fake.start()
    yield fake
    fake.stop()


@pytest.fixture
async def api(device):
    """Provide an API client pointed at the fake device."""
    client = MarstekAPI("127.0.0.1", device.port, timeout=0.5)
    yield client
    await client.async_close()


async def test_request_returns_result(api, device):
    """A normal request returns the device's result object."""
    device.results["Marstek.GetDevice"] = {"device": "VenusE", "ble_mac": "abc123"}
    result = await api.async_request("Marstek.GetDevice")
    assert result == {"device": "VenusE", "ble_mac": "abc123"}


async def test_each_request_gets_a_fresh_id(api, device):
    """Ids must not be reused, or responses cannot be matched to requests."""
    await api.async_request("Bat.GetStatus")
    await api.async_request("ES.GetStatus")
    ids = [request["id"] for request in device.requests]
    assert len(set(ids)) == len(ids)


async def test_concurrent_requests_do_not_cross(api, device):
    """Concurrent replies must land on their own request, not the next one.

    The slow command is answered after the fast ones, which is exactly the
    ordering that makes an id-less client attribute values to the wrong field.
    """
    device.results = {
        "Bat.GetStatus": {"soc": 55},
        "ES.GetStatus": {"bat_power": -800},
        "EM.GetStatus": {"total_power": 120},
    }
    device.behaviour["Bat.GetStatus"] = 0.25

    battery, es, em = await asyncio.gather(
        api.async_request("Bat.GetStatus"),
        api.async_request("ES.GetStatus"),
        api.async_request("EM.GetStatus"),
    )

    assert battery == {"soc": 55}
    assert es == {"bat_power": -800}
    assert em == {"total_power": 120}


async def test_timeout_after_retries(api, device):
    """An unanswered command raises after exhausting its retries."""
    device.behaviour["ES.GetStatus"] = "drop"
    with pytest.raises(MarstekTimeout):
        await api.async_request("ES.GetStatus")
    assert len(device.requests) == 2  # REQUEST_RETRIES


async def test_device_error_is_not_retried(api, device):
    """An explicit rejection fails immediately instead of being resent."""
    device.behaviour["DOD.SET"] = "error"
    with pytest.raises(MarstekDeviceError):
        await api.async_request("DOD.SET", {"value": 50})
    assert len(device.requests) == 1


async def test_datagram_from_other_host_is_ignored(api, device):
    """A reply from a different device must not resolve our request.

    This is the multi-device case: two storage units on one network, each with
    its own config entry.
    """
    device.behaviour["ES.GetStatus"] = "drop"
    task = asyncio.create_task(api.async_request("ES.GetStatus"))
    await asyncio.sleep(0.05)

    # Impersonate a second device answering with the id we are waiting for.
    intruder = list(api._pending)[0]
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.2", 0)
    )
    local_port = api._transport.get_extra_info("sockname")[1]
    transport.sendto(
        json.dumps({"id": intruder, "src": "other", "result": {"soc": 99}}).encode(),
        ("127.0.0.1", local_port),
    )

    try:
        with pytest.raises(MarstekTimeout):
            await task
    finally:
        transport.close()


async def test_partial_failure_reports_none_per_endpoint(api, device):
    """get_all_data reports None only for the endpoints that went unanswered."""
    device.results["Bat.GetStatus"] = {"soc": 42}
    device.behaviour["EM.GetStatus"] = "drop"

    data = await api.get_all_data()

    assert data["battery"] == {"soc": 42}
    assert data["em_status"] is None
    assert data["es_status"] is not None


async def test_set_passive_power_sends_sign_corrected_command(api, device):
    """set_passive_power emits one ES.SetMode carrying power and countdown."""
    device.results["ES.SetMode"] = {"set_result": True}

    assert await api.set_passive_power(-800, 30) is True

    sent = [r for r in device.requests if r["method"] == "ES.SetMode"][0]
    config = sent["params"]["config"]
    assert config["mode"] == "Passive"
    assert config["passive_cfg"] == {"power": -800, "cd_time": 30}


async def test_set_mode_reports_failure(api, device):
    """A command the device does not confirm is reported as failed."""
    device.results["ES.SetMode"] = {"set_result": False}
    assert await api.set_es_mode("Auto") is False


async def test_requests_are_never_in_flight_together(api, device) -> None:
    """The device must never be handed a second request while it is busy.

    The hardware serves one request at a time and silently drops anything that
    arrives meanwhile, so a poll that fires its commands concurrently loses
    most of the answers. Every command is given a response delay here, which
    would overlap immediately if the client sent them in parallel.
    """
    for method in (
        "Marstek.GetDevice",
        "Bat.GetStatus",
        "ES.GetMode",
        "ES.GetStatus",
        "EM.GetStatus",
        "Wifi.GetStatus",
    ):
        device.behaviour[method] = 0.05

    data = await api.get_all_data()

    assert device.max_in_flight == 1
    assert all(value is not None for value in data.values())


async def test_explicitly_concurrent_callers_are_serialized(api, device) -> None:
    """Even callers that gather requests must not overlap on the wire."""
    device.behaviour["Bat.GetStatus"] = 0.05
    device.behaviour["ES.GetStatus"] = 0.05

    await asyncio.gather(
        api.async_request("Bat.GetStatus"),
        api.async_request("ES.GetStatus"),
    )

    assert device.max_in_flight == 1


async def test_poll_budget_stops_a_silent_device_from_stalling(api, device) -> None:
    """A device that stops answering must not hold the poll open indefinitely."""
    for method in list(device.behaviour) + [
        "Marstek.GetDevice",
        "Bat.GetStatus",
        "ES.GetMode",
        "ES.GetStatus",
        "EM.GetStatus",
        "Wifi.GetStatus",
    ]:
        device.behaviour[method] = "drop"

    loop = asyncio.get_running_loop()
    started = loop.time()
    data = await api.get_all_data(budget=1.5)
    elapsed = loop.time() - started

    # Without the budget this would take 6 endpoints * 2 attempts * 0.5s = 6s.
    assert elapsed < 3.0
    assert all(value is None for value in data.values())
