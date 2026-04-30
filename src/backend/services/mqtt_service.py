import asyncio
import json
from typing import Callable, Awaitable

import aiomqtt

from utils.logger import get_logger

logger = get_logger("mqtt_service")


def parse_zigbee_message(topic: str, payload: str) -> dict | None:
    """Parse a Zigbee2MQTT message into a structured event or None if irrelevant."""
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != "zigbee2mqtt":
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    # Bridge events (device_joined, device_announce, etc.)
    if len(parts) >= 3 and parts[1] == "bridge" and parts[2] == "event":
        event_type = data.get("type", "")
        event_data = data.get("data", {})
        if event_type in ("device_joined", "device_announce"):
            ieee = event_data.get("ieee_address", "")
            if ieee:
                return {
                    "type": event_type,
                    "ieee_addr": ieee,
                    "friendly_name": event_data.get("friendly_name", ieee),
                }
        return None

    # Other bridge topics — ignore
    if len(parts) >= 2 and parts[1] == "bridge":
        return None

    # Device messages (button actions)
    ieee_addr = parts[1]
    action = data.get("action")
    if action:
        return {
            "type": "button_action",
            "ieee_addr": ieee_addr,
            "action": action,
            "battery": data.get("battery"),
            "linkquality": data.get("linkquality"),
        }

    return None


class MQTTService:
    def __init__(self, host: str = "localhost", port: int = 1883, ws_manager=None):
        self._host = host
        self._port = port
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._on_message: Callable[[dict], Awaitable[None]] | None = None
        self._ws = ws_manager
        self._connected = False

    def set_handler(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._on_message = handler

    def is_connected(self) -> bool:
        return self._connected

    async def _set_connected(self, state: bool) -> None:
        if self._connected == state:
            return
        self._connected = state
        logger.info(f"MQTT connection state -> {'connected' if state else 'disconnected'}")
        if self._ws:
            await self._ws.broadcast("mqtt:state", {"connected": state})

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())
        logger.info(f"MQTT service started, connecting to {self._host}:{self._port}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._set_connected(False)
        logger.info("MQTT service stopped")

    async def publish(self, topic: str, payload: dict) -> None:
        if self._client:
            await self._client.publish(topic, json.dumps(payload))

    async def permit_join(self, enable: bool, time: int = 120) -> None:
        await self.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            {"value": enable, "time": time},
        )
        logger.info(f"permit_join={'enabled' if enable else 'disabled'}, time={time}s")

    async def _listen(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(self._host, self._port) as client:
                    self._client = client
                    await client.subscribe("zigbee2mqtt/#")
                    logger.info("Subscribed to zigbee2mqtt/#")
                    await self._set_connected(True)
                    async for message in client.messages:
                        topic = str(message.topic)
                        payload = message.payload.decode() if message.payload else ""
                        parsed = parse_zigbee_message(topic, payload)
                        if parsed and self._on_message:
                            try:
                                await self._on_message(parsed)
                            except Exception as e:
                                logger.error(f"Handler error: {e}")
            except aiomqtt.MqttError as e:
                logger.warning(f"MQTT connection lost: {e}. Reconnecting in 5s...")
                self._client = None
                await self._set_connected(False)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self._client = None
                await self._set_connected(False)
                raise
