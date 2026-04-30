import pytest
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.mqtt_service import parse_zigbee_message, MQTTService


class FakeWS:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


def test_parse_button_action():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "single", "battery": 95, "linkquality": 120})
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "button_action"
    assert result["ieee_addr"] == "0x00124b00abcdef"
    assert result["action"] == "single"


def test_parse_button_action_double():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "double"})
    result = parse_zigbee_message(topic, payload)
    assert result["action"] == "double"


def test_parse_button_action_long():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "long"})
    result = parse_zigbee_message(topic, payload)
    assert result["action"] == "long"


def test_parse_empty_action_ignored():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "", "battery": 95})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_device_joined():
    topic = "zigbee2mqtt/bridge/event"
    payload = json.dumps({
        "type": "device_joined",
        "data": {"friendly_name": "0x00124b00ffffff", "ieee_address": "0x00124b00ffffff"}
    })
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "device_joined"
    assert result["ieee_addr"] == "0x00124b00ffffff"


def test_parse_bridge_state_ignored():
    topic = "zigbee2mqtt/bridge/state"
    payload = json.dumps({"state": "online"})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_non_action_device_message_ignored():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"battery": 95, "linkquality": 120})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_device_announce():
    topic = "zigbee2mqtt/bridge/event"
    payload = json.dumps({
        "type": "device_announce",
        "data": {"friendly_name": "0x00124b00abcdef", "ieee_address": "0x00124b00abcdef"}
    })
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "device_announce"
    assert result["ieee_addr"] == "0x00124b00abcdef"


# ── connection state tracking (CORNER-001 / IT-16) ──────────────────


@pytest.mark.asyncio
async def test_mqtt_service_starts_disconnected():
    ws = FakeWS()
    svc = MQTTService(host="localhost", port=1883, ws_manager=ws)
    assert svc.is_connected() is False
    assert ws.events == []


@pytest.mark.asyncio
async def test_mqtt_service_set_connected_broadcasts_on_transition():
    ws = FakeWS()
    svc = MQTTService(host="localhost", port=1883, ws_manager=ws)

    await svc._set_connected(True)
    assert svc.is_connected() is True
    assert ws.events == [("mqtt:state", {"connected": True})]


@pytest.mark.asyncio
async def test_mqtt_service_set_connected_dedups_same_state():
    ws = FakeWS()
    svc = MQTTService(host="localhost", port=1883, ws_manager=ws)

    await svc._set_connected(True)
    await svc._set_connected(True)
    await svc._set_connected(False)
    await svc._set_connected(False)

    assert [ev[1]["connected"] for ev in ws.events] == [True, False]


@pytest.mark.asyncio
async def test_mqtt_service_no_ws_manager_does_not_crash():
    svc = MQTTService(host="localhost", port=1883)
    await svc._set_connected(True)
    assert svc.is_connected() is True
