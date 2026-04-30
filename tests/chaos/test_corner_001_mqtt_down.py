"""
CORNER-001: MQTT broker down → button silent failure.

Scenario:
  Mosquitto is killed. Frontend has no idea — button presses go nowhere,
  no banner is shown, /api/health still says ok.

Pass criteria (the bug we expect to find):
  - /api/health should expose mqtt connectivity
  - WS should broadcast a connection_state event when MQTT drops
  - Backend should log MQTT disconnect + reconnect attempts

Likely outcome: this test will FAIL on at least one assertion.
That failure IS the documented gap (CORNER-001).
"""
import asyncio
import json
import time

import pytest
import websockets


pytestmark = [pytest.mark.chaos, pytest.mark.batch1]


@pytest.mark.asyncio
async def test_health_should_expose_mqtt_state(chaos):
    """health endpoint should reveal MQTT broker connectivity."""
    # Baseline
    assert chaos.mosquitto_running(), "Mosquitto should be running before test"
    health = chaos.get_health()
    print(f"\n[baseline] health = {health}")

    # Disrupt
    chaos.stop_mosquitto()
    time.sleep(8)  # allow backend to notice

    health_during = chaos.get_health()
    print(f"[mqtt-down] health = {health_during}")

    # Restore happens via safety_finalizer; assertion below is the actual check
    assert "mqtt" in health_during or "mqtt_connected" in health_during, (
        f"GAP: /api/health does not expose MQTT state. "
        f"Frontend has no way to know broker is down. Got: {health_during}"
    )


@pytest.mark.asyncio
async def test_ws_should_broadcast_mqtt_disconnect(chaos, ws_url):
    """WS should push a connection-state event when MQTT drops."""
    assert chaos.mosquitto_running()

    received = []

    async def collect():
        async with websockets.connect(ws_url) as ws:
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    received.append(json.loads(msg))
            except asyncio.TimeoutError:
                pass

    # Start collector in background
    collector_task = asyncio.create_task(_collect_for(ws_url, received, duration=15))
    await asyncio.sleep(2)  # let WS connect

    # Disrupt MQTT
    chaos.stop_mosquitto()
    await asyncio.sleep(10)  # backend should notice + push event

    await collector_task  # finishes after 15s

    print(f"\n[ws] events seen during MQTT outage: {len(received)}")
    for ev in received[:20]:
        print(f"  {ev.get('event')}: {ev.get('data')}")

    mqtt_events = [
        ev for ev in received
        if "mqtt" in str(ev.get("event", "")).lower()
        or "mqtt" in json.dumps(ev.get("data", {})).lower()
    ]
    assert mqtt_events, (
        f"GAP: no MQTT-related WS event during 10s outage. "
        f"Got {len(received)} events, none mention MQTT."
    )


@pytest.mark.asyncio
async def test_backend_logs_mqtt_disconnect_and_reconnect(chaos):
    """After stop+start, app logs should show disconnect detection + successful reconnect."""
    assert chaos.mosquitto_running()

    # Disrupt
    chaos.stop_mosquitto()
    time.sleep(8)

    # Restore (don't wait for finalizer — we want to verify reconnect happens)
    chaos.start_mosquitto()
    time.sleep(12)  # backend reconnect delay is 5s; give buffer

    logs = chaos.app_logs(n=300)
    print(f"\n[logs tail 300]\n{logs[-2000:]}")

    has_disconnect = "MQTT connection lost" in logs or "Reconnecting" in logs
    has_reconnect = "MQTT service started" in logs or "subscribe" in logs.lower()

    assert has_disconnect, "GAP: backend logs do not mention MQTT disconnect"
    assert has_reconnect, "GAP: backend logs do not show MQTT reconnect"


async def _collect_for(ws_url, sink, duration):
    deadline = asyncio.get_event_loop().time() + duration
    try:
        async with websockets.connect(ws_url) as ws:
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    sink.append(json.loads(msg))
                except asyncio.TimeoutError:
                    break
    except Exception as e:
        print(f"[ws collector] error: {e}")
