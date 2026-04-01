import pytest
import pytest_asyncio
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.command_queue import CommandQueue, QueueItem


class FakeActionExecutor:
    def __init__(self):
        self.calls = []
        self.delay = 0

    async def execute(self, robot_id, action, params):
        if self.delay:
            await asyncio.sleep(self.delay)
        self.calls.append((robot_id, action, params))
        return {"ok": True, "action": action}


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


class FakeRobotManager:
    def __init__(self):
        self._cancel_calls = []

    def get(self, robot_id):
        return FakeRobotService(self._cancel_calls)


class FakeRobotService:
    def __init__(self, cancel_calls):
        self.commands = FakeCommands(cancel_calls)


class FakeCommands:
    def __init__(self, cancel_calls):
        self._cancel_calls = cancel_calls

    def cancel_command(self):
        self._cancel_calls.append(True)
        return {"ok": True}


@pytest_asyncio.fixture
async def setup(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    executor = FakeActionExecutor()
    ws = FakeWSManager()
    rm = FakeRobotManager()
    queue = CommandQueue(
        action_executor=executor,
        robot_manager=rm,
        ws_manager=ws,
        db=db,
    )
    yield queue, executor, ws, rm, db
    await disconnect()


@pytest.mark.asyncio
async def test_enqueue_adds_item(setup):
    queue, executor, ws, _, _ = setup
    result = await queue.enqueue("r1", "return_home", {})
    assert result["ok"] is True
    assert "queue_id" in result
    items = queue.get_all()
    assert len(items) == 1
    assert items[0]["action"] == "return_home"
    assert items[0]["robot_id"] == "r1"
    assert items[0]["status"] in ("pending", "executing")


@pytest.mark.asyncio
async def test_enqueue_debounce_consecutive(setup):
    queue, executor, ws, _, _ = setup
    executor.delay = 0.5
    await queue.enqueue("r1", "return_home", {})
    r1 = await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    assert r1["ok"] is True
    r2 = await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    assert r2["ok"] is False
    assert "debounce" in r2["error"].lower()


@pytest.mark.asyncio
async def test_enqueue_allows_non_consecutive_duplicates(setup):
    queue, executor, ws, _, _ = setup
    executor.delay = 0.5
    await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    await queue.enqueue("r1", "return_home", {})
    r = await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_get_all_empty(setup):
    queue, _, _, _, _ = setup
    assert queue.get_all() == []


@pytest.mark.asyncio
async def test_set_enabled(setup):
    queue, _, _, _, _ = setup
    assert queue.enabled is True
    queue.set_enabled(False)
    assert queue.enabled is False


@pytest.mark.asyncio
async def test_worker_executes_sequentially(setup):
    queue, executor, ws, _, db = setup
    executor.delay = 0.05
    await queue.enqueue("r1", "return_home", {}, button_id=1, trigger="single")
    await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"}, button_id=1, trigger="double")
    await asyncio.sleep(0.3)
    assert len(executor.calls) == 2
    assert executor.calls[0] == ("r1", "return_home", {})
    assert executor.calls[1] == ("r1", "move_to_location", {"name": "Kitchen"})
    async with db.execute("SELECT action FROM action_logs ORDER BY id") as cursor:
        rows = await cursor.fetchall()
    assert [r[0] for r in rows] == ["return_home", "move_to_location"]


@pytest.mark.asyncio
async def test_worker_broadcasts_events(setup):
    queue, executor, ws, _, _ = setup
    await queue.enqueue("r1", "return_home", {})
    await asyncio.sleep(0.1)
    event_types = [e[0] for e in ws.events]
    assert "queue:added" in event_types
    assert "queue:executing" in event_types
    assert "queue:completed" in event_types
    assert "action_executed" in event_types


@pytest.mark.asyncio
async def test_remove_pending_item(setup):
    queue, executor, ws, _, _ = setup
    executor.delay = 0.5
    await queue.enqueue("r1", "return_home", {})
    r = await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    queue_id = r["queue_id"]
    result = await queue.remove(queue_id)
    assert result["ok"] is True
    items = queue.get_all()
    assert all(i["action"] != "move_to_location" for i in items)


@pytest.mark.asyncio
async def test_remove_nonexistent(setup):
    queue, _, _, _, _ = setup
    result = await queue.remove("nonexistent-id")
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_cancel_current_no_command(setup):
    queue, _, _, _, _ = setup
    result = await queue.cancel_current("r1")
    assert result["ok"] is True
    assert result.get("message") == "no command running"


@pytest.mark.asyncio
async def test_cancel_current_with_command(setup):
    queue, executor, ws, rm, _ = setup
    executor.delay = 1.0
    await queue.enqueue("r1", "return_home", {})
    await asyncio.sleep(0.05)
    result = await queue.cancel_current("r1")
    assert result["ok"] is True
    assert len(rm._cancel_calls) == 1
    event_types = [e[0] for e in ws.events]
    assert "queue:cancelled" in event_types


@pytest.mark.asyncio
async def test_disabled_idle_executes_directly(setup):
    queue, executor, ws, _, db = setup
    queue.set_enabled(False)
    result = await queue.enqueue("r1", "return_home", {}, button_id=1, trigger="single")
    assert result["ok"] is True
    assert result["action"] == "return_home"
    assert len(executor.calls) == 1
    async with db.execute("SELECT COUNT(*) FROM action_logs") as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 1


@pytest.mark.asyncio
async def test_disabled_busy_rejects(setup):
    queue, executor, ws, _, _ = setup
    queue.set_enabled(False)
    executor.delay = 1.0
    task = asyncio.create_task(queue.enqueue("r1", "return_home", {}))
    await asyncio.sleep(0.05)
    result = await queue.enqueue("r1", "move_to_location", {"name": "Kitchen"})
    assert result["ok"] is False
    assert "busy" in result["error"].lower()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
