"""End-to-end test: dispatch route -> execute stops -> timeout -> complete."""
import pytest
import pytest_asyncio
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.route_dispatcher import RouteDispatcher
from services.route_service import RouteService


class FakeActionExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, robot_id, action, params):
        self.calls.append((robot_id, action, params))
        return {"ok": True, "action": action}


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


class FakeRobotManager:
    def __init__(self):
        self._ids = ["r1", "r2"]

    def all_ids(self):
        return list(self._ids)

    def get(self, robot_id):
        return robot_id in self._ids or None


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
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r2", "Robot B", "1.2.3.5"),
    )
    await db.commit()

    executor = FakeActionExecutor()
    ws = FakeWSManager()
    rm = FakeRobotManager()
    notifier = FakeNotifier()

    dispatcher = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    route_svc = RouteService(
        db=db, action_executor=executor, ws_manager=ws, notifier=notifier,
    )
    dispatcher.set_route_service(route_svc)
    route_svc.set_dispatcher(dispatcher)

    yield dispatcher, route_svc, executor, ws, notifier, db

    for task in list(route_svc._tasks.values()):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await disconnect()


@pytest.mark.asyncio
async def test_full_route_lifecycle(setup):
    """Dispatch a 2-stop route with 1s timeout. Verify complete lifecycle."""
    dispatcher, route_svc, executor, ws, notifier, db = setup

    result = await dispatcher.dispatch(
        stops=[{"name": "A"}, {"name": "B"}],
        default_timeout=1,
        shelf_name="ShelfX",
    )
    assert result["ok"] is True
    run_id = result["run_id"]

    # Wait for the full route to complete (2 stops x 1s timeout + move time + cleanup)
    await asyncio.sleep(5.0)

    # Verify executor calls: move_shelf for A and B, then return_shelf + return_home
    actions = [c[1] for c in executor.calls]
    move_calls = [c for c in executor.calls if c[1] == "move_shelf"]
    assert len(move_calls) == 2
    assert move_calls[0][2] == {"shelf": "ShelfX", "location": "A"}
    assert move_calls[1][2] == {"shelf": "ShelfX", "location": "B"}
    assert "return_shelf" in actions
    assert "return_home" in actions
    # Verify return_shelf has shelf name
    return_calls = [c for c in executor.calls if c[1] == "return_shelf"]
    assert return_calls[0][2] == {"shelf": "ShelfX"}

    # Verify 2 timeout notifications sent (one per stop)
    assert len(notifier.messages) == 2

    # Verify DB status = completed
    async with db.execute("SELECT status FROM route_runs WHERE id = ?", (run_id,)) as c:
        row = await c.fetchone()
    assert row[0] == "completed"

    # Verify 2 stop_logs written
    async with db.execute(
        "SELECT COUNT(*) FROM route_stop_logs WHERE run_id = ?", (run_id,)
    ) as c:
        count = (await c.fetchone())[0]
    assert count == 2

    # Verify WebSocket events include key lifecycle events
    event_types = [e[0] for e in ws.events]
    assert "route:assigned" in event_types
    assert "route:running" in event_types
    assert "route:moving" in event_types
    assert "route:waiting" in event_types
    assert "route:completed" in event_types


@pytest.mark.asyncio
async def test_round_robin_two_routes(setup):
    """Dispatch 2 routes. Verify r1 gets first, r2 gets second. Both complete."""
    dispatcher, route_svc, executor, ws, notifier, db = setup

    r1 = await dispatcher.dispatch(
        stops=[{"name": "A"}],
        default_timeout=1,
        shelf_name="ShelfX",
    )
    r2 = await dispatcher.dispatch(
        stops=[{"name": "B"}],
        default_timeout=1,
        shelf_name="ShelfY",
    )
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r1["robot_id"] == "r1"
    assert r2["robot_id"] == "r2"

    # Wait for both routes to complete
    await asyncio.sleep(5.0)

    # Verify both completed in DB
    for run_id in [r1["run_id"], r2["run_id"]]:
        async with db.execute(
            "SELECT status FROM route_runs WHERE id = ?", (run_id,)
        ) as c:
            row = await c.fetchone()
        assert row[0] == "completed", f"Run {run_id} expected completed, got {row[0]}"


class SlowExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, robot_id, action, params):
        self.calls.append((robot_id, action, params))
        if action in ("move_to_location", "move_shelf"):
            await asyncio.sleep(2.0)
        return {"ok": True}


@pytest.mark.asyncio
async def test_queue_and_dequeue(setup):
    """Dispatch 3 routes to 2 robots. Third gets queued, then dequeued when one finishes."""
    dispatcher, route_svc, executor, ws, notifier, db = setup

    # Replace executor with slow version
    slow = SlowExecutor()
    route_svc._executor = slow

    r1 = await dispatcher.dispatch(
        stops=[{"name": "A"}],
        default_timeout=1,
        shelf_name="ShelfX",
    )
    r2 = await dispatcher.dispatch(
        stops=[{"name": "B"}],
        default_timeout=1,
        shelf_name="ShelfY",
    )
    r3 = await dispatcher.dispatch(
        stops=[{"name": "C"}],
        default_timeout=1,
        shelf_name="ShelfX",
    )

    assert r1["robot_id"] == "r1"
    assert r2["robot_id"] == "r2"
    assert r3["status"] == "queued"
    assert r3["robot_id"] is None

    # Wait for all routes to complete (2s move + 1s timeout + cleanup per route, sequential for queued)
    await asyncio.sleep(15.0)

    # Verify all three completed in DB
    for run_id in [r1["run_id"], r2["run_id"], r3["run_id"]]:
        async with db.execute(
            "SELECT status FROM route_runs WHERE id = ?", (run_id,)
        ) as c:
            row = await c.fetchone()
        assert row[0] == "completed", f"Run {run_id} expected completed, got {row[0]}"

    # Verify the queued route got a robot_id assigned
    async with db.execute(
        "SELECT robot_id FROM route_runs WHERE id = ?", (r3["run_id"],)
    ) as c:
        row = await c.fetchone()
    assert row[0] is not None, "Queued route should have been assigned a robot"
