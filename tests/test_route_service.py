import pytest
import pytest_asyncio
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.route_service import RouteService


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


class FakeDispatcher:
    def __init__(self):
        self.done_calls = []

    async def on_route_done(self, run_id, robot_id):
        self.done_calls.append((run_id, robot_id))


class FakeNotifier:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)
        return True


@pytest_asyncio.fixture
async def setup(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot A", "1.2.3.4"),
    )
    await db.commit()

    executor = FakeActionExecutor()
    ws = FakeWSManager()
    dispatcher = FakeDispatcher()
    notifier = FakeNotifier()
    svc = RouteService(
        db=db, action_executor=executor, ws_manager=ws, notifier=notifier,
    )
    svc.set_dispatcher(dispatcher)
    yield svc, executor, ws, dispatcher, notifier, db
    for task in list(svc._tasks.values()):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await disconnect()


async def _insert_run(db, run_id, stops, robot_id="r1", default_timeout=2, confirm_button_id=None, shelf_name="TestShelf"):
    await db.execute(
        "INSERT INTO route_runs (id, robot_id, stops, default_timeout, confirm_button_id, "
        "shelf_name, status, current_stop) VALUES (?, ?, ?, ?, ?, ?, 'assigned', -1)",
        (run_id, robot_id, json.dumps(stops), default_timeout, confirm_button_id, shelf_name),
    )
    await db.commit()


@pytest.mark.asyncio
async def test_run_completes_all_stops_with_timeout(setup):
    svc, executor, ws, dispatcher, notifier, db = setup
    stops = [{"name": "A"}, {"name": "B"}]
    await _insert_run(db, "run-1", stops, default_timeout=1)
    await svc.start_run("run-1", "r1")
    await asyncio.sleep(3.0)
    actions = [c[1] for c in executor.calls]
    assert actions[0] == "move_shelf"
    assert actions[1] == "move_shelf"
    assert "return_shelf" in actions
    assert "return_home" in actions
    # Verify move_shelf params include shelf name
    move_calls = [c for c in executor.calls if c[1] == "move_shelf"]
    assert move_calls[0][2] == {"shelf": "TestShelf", "location": "A"}
    assert move_calls[1][2] == {"shelf": "TestShelf", "location": "B"}
    # Verify return_shelf includes shelf name
    return_calls = [c for c in executor.calls if c[1] == "return_shelf"]
    assert return_calls[0][2] == {"shelf": "TestShelf"}
    assert len(notifier.messages) == 2
    assert ("run-1", "r1") in dispatcher.done_calls
    async with db.execute("SELECT status FROM route_runs WHERE id = 'run-1'") as c:
        row = await c.fetchone()
    assert row[0] == "completed"
    async with db.execute("SELECT COUNT(*) FROM route_stop_logs WHERE run_id = 'run-1'") as c:
        count = (await c.fetchone())[0]
    assert count == 2


@pytest.mark.asyncio
async def test_button_confirm_skips_timeout(setup):
    svc, executor, ws, dispatcher, notifier, db = setup
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0xAABB", "Confirm Btn"),
    )
    await db.commit()
    async with db.execute("SELECT id FROM buttons WHERE ieee_addr = '0xAABB'") as c:
        btn_id = (await c.fetchone())[0]
    stops = [{"name": "A"}]
    await _insert_run(db, "run-2", stops, default_timeout=30, confirm_button_id=btn_id)
    await svc.start_run("run-2", "r1")
    await asyncio.sleep(0.3)
    confirmed = svc.try_confirm("0xAABB")
    assert confirmed is True
    await asyncio.sleep(1.0)
    assert len(notifier.messages) == 0
    assert ("run-2", "r1") in dispatcher.done_calls


@pytest.mark.asyncio
async def test_cancel_run(setup):
    svc, executor, ws, dispatcher, notifier, db = setup
    stops = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    await _insert_run(db, "run-3", stops, default_timeout=30)
    await svc.start_run("run-3", "r1")
    await asyncio.sleep(0.3)
    await svc.cancel_run("run-3")
    await asyncio.sleep(2.0)
    actions = [c[1] for c in executor.calls]
    assert "return_shelf" in actions
    assert "return_home" in actions
    async with db.execute("SELECT status FROM route_runs WHERE id = 'run-3'") as c:
        row = await c.fetchone()
    assert row[0] == "cancelled"
    assert ("run-3", "r1") in dispatcher.done_calls


@pytest.mark.asyncio
async def test_per_stop_timeout_override(setup):
    svc, executor, ws, dispatcher, notifier, db = setup
    stops = [{"name": "A", "timeout_sec": 1}]
    await _insert_run(db, "run-4", stops, default_timeout=60)
    await svc.start_run("run-4", "r1")
    await asyncio.sleep(2.5)
    assert len(notifier.messages) == 1
    assert ("run-4", "r1") in dispatcher.done_calls


@pytest.mark.asyncio
async def test_get_active_runs(setup):
    svc, executor, ws, dispatcher, notifier, db = setup
    executor.delay = 5.0
    stops = [{"name": "A"}]
    await _insert_run(db, "run-5", stops, default_timeout=30)
    await svc.start_run("run-5", "r1")
    await asyncio.sleep(0.1)
    active = svc.get_active_runs()
    assert "run-5" in active
    assert active["run-5"]["robot_id"] == "r1"
