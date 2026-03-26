import pytest
import pytest_asyncio
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.ws_manager import WSManager


class FakeWebSocket:
    def __init__(self):
        self.messages = []
        self.accepted = False
        self.closed = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text: str):
        if self.closed:
            raise Exception("Connection closed")
        self.messages.append(json.loads(text))

    async def receive_text(self):
        await asyncio.sleep(100)


@pytest.mark.asyncio
async def test_connect_and_broadcast():
    mgr = WSManager()
    ws = FakeWebSocket()
    await mgr.connect(ws)
    assert ws.accepted
    await mgr.broadcast("test_event", {"key": "value"})
    assert len(ws.messages) == 1
    assert ws.messages[0] == {"event": "test_event", "data": {"key": "value"}}


@pytest.mark.asyncio
async def test_disconnect_removes_ws():
    mgr = WSManager()
    ws = FakeWebSocket()
    await mgr.connect(ws)
    mgr.disconnect(ws)
    await mgr.broadcast("test_event", {})
    assert len(ws.messages) == 0


@pytest.mark.asyncio
async def test_broadcast_removes_broken_connections():
    mgr = WSManager()
    ws_ok = FakeWebSocket()
    ws_broken = FakeWebSocket()
    ws_broken.closed = True
    await mgr.connect(ws_ok)
    await mgr.connect(ws_broken)
    await mgr.broadcast("test_event", {"a": 1})
    assert len(ws_ok.messages) == 1
    assert ws_broken not in mgr._connections
