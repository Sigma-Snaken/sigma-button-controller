import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.action_executor import ActionExecutor
from services.robot_manager import RobotManager


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip
        self.serial = "KCK-TEST"
    def ping(self):
        return {"ok": True, "serial": self.serial}


class FakeCommands:
    def __init__(self, conn):
        self.last_call = None
    def move_to_location(self, name):
        self.last_call = ("move_to_location", name)
        return {"ok": True, "action": "move_to_location", "target": name}
    def return_home(self):
        self.last_call = ("return_home",)
        return {"ok": True, "action": "return_home"}
    def speak(self, text):
        self.last_call = ("speak", text)
        return {"ok": True, "action": "speak"}
    def move_shelf(self, shelf, location):
        self.last_call = ("move_shelf", shelf, location)
        return {"ok": True, "action": "move_shelf"}
    def return_shelf(self, shelf=None):
        self.last_call = ("return_shelf", shelf)
        return {"ok": True, "action": "return_shelf"}
    def dock_shelf(self):
        self.last_call = ("dock_shelf",)
        return {"ok": True, "action": "dock_shelf"}
    def undock_shelf(self):
        self.last_call = ("undock_shelf",)
        return {"ok": True, "action": "undock_shelf"}
    def start_shortcut(self, shortcut_id):
        self.last_call = ("start_shortcut", shortcut_id)
        return {"ok": True, "action": "start_shortcut"}
    def reset_shelf_pose(self, shelf_name):
        self.last_call = ("reset_shelf_pose", shelf_name)
        return {"ok": True, "action": "reset_shelf_pose", "target": shelf_name}


class FakeQueries:
    def __init__(self, conn):
        pass


@pytest.fixture
def executor():
    mgr = RobotManager()
    mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
            commands_cls=FakeCommands, queries_cls=FakeQueries)
    return ActionExecutor(mgr)


@pytest.mark.asyncio
async def test_move_to_location(executor):
    result = await executor.execute("r1", "move_to_location", {"name": "Kitchen"})
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_return_home(executor):
    result = await executor.execute("r1", "return_home", {})
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_speak(executor):
    result = await executor.execute("r1", "speak", {"text": "你好"})
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_start_shortcut(executor):
    result = await executor.execute("r1", "start_shortcut", {"shortcut_id": "sc-1"})
    assert result["ok"] is True

@pytest.mark.asyncio
async def test_reset_shelf(executor):
    result = await executor.execute("r1", "reset_shelf", {"shelf": "ShelfA"})
    assert result["ok"] is True
    assert result["target"] == "ShelfA"

@pytest.mark.asyncio
async def test_unknown_action(executor):
    result = await executor.execute("r1", "fly_away", {})
    assert result["ok"] is False
    assert "Unknown action" in result["error"]

@pytest.mark.asyncio
async def test_unknown_robot(executor):
    result = await executor.execute("nonexistent", "return_home", {})
    assert result["ok"] is False
    assert "not found" in result["error"]
