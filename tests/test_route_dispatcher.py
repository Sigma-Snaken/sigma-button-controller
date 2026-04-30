import pytest
import pytest_asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.route_dispatcher import RouteDispatcher


class FakeRouteService:
    def __init__(self):
        self.started_runs = []

    async def start_run(self, run_id: str, robot_id: str):
        self.started_runs.append((run_id, robot_id))


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


class FakeRobotManager:
    def __init__(self, robot_ids=None):
        self._ids = robot_ids or ["r1", "r2"]

    def all_ids(self):
        return list(self._ids)

    def get(self, robot_id):
        return robot_id in self._ids or None


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
    ws = FakeWSManager()
    rm = FakeRobotManager()
    route_svc = FakeRouteService()
    dispatcher = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher.set_route_service(route_svc)
    yield dispatcher, route_svc, ws, rm, db
    await disconnect()


@pytest.mark.asyncio
async def test_dispatch_round_robin(setup):
    dispatcher, route_svc, ws, _, _ = setup
    r1 = await dispatcher.dispatch(stops=[{"name": "A"}, {"name": "B"}], default_timeout=120)
    assert r1["ok"] is True
    assert r1["robot_id"] == "r1"
    # Free r1 so r2 gets next assignment
    await dispatcher.on_route_done(r1["run_id"], "r1")
    r2 = await dispatcher.dispatch(stops=[{"name": "C"}], default_timeout=120)
    assert r2["ok"] is True
    assert r2["robot_id"] == "r2"
    # Free r2 so round-robin wraps back to r1
    await dispatcher.on_route_done(r2["run_id"], "r2")
    r3 = await dispatcher.dispatch(stops=[{"name": "D"}], default_timeout=120)
    assert r3["ok"] is True
    assert r3["robot_id"] == "r1"


@pytest.mark.asyncio
async def test_dispatch_pinned_robot(setup):
    dispatcher, route_svc, _, _, _ = setup
    r = await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120, pinned_robot_id="r2")
    assert r["ok"] is True
    assert r["robot_id"] == "r2"


@pytest.mark.asyncio
async def test_dispatch_queues_when_busy(setup):
    dispatcher, route_svc, ws, _, db = setup
    r1 = await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    r2 = await dispatcher.dispatch(stops=[{"name": "B"}], default_timeout=120)
    r3 = await dispatcher.dispatch(stops=[{"name": "C"}], default_timeout=120)
    assert r3["ok"] is True
    assert r3["status"] == "queued"
    assert r3["robot_id"] is None
    async with db.execute("SELECT status FROM route_runs WHERE id = ?", (r3["run_id"],)) as c:
        row = await c.fetchone()
    assert row[0] == "queued"


@pytest.mark.asyncio
async def test_on_route_done_dequeues(setup):
    dispatcher, route_svc, ws, _, _ = setup
    r1 = await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    r2 = await dispatcher.dispatch(stops=[{"name": "B"}], default_timeout=120)
    r3 = await dispatcher.dispatch(stops=[{"name": "C"}], default_timeout=120)
    assert r3["status"] == "queued"
    await dispatcher.on_route_done(r1["run_id"], "r1")
    assert len(route_svc.started_runs) == 3
    assert route_svc.started_runs[2] == (r3["run_id"], "r1")


@pytest.mark.asyncio
async def test_dispatch_from_template(setup):
    dispatcher, route_svc, _, _, db = setup
    import json
    await db.execute(
        "INSERT INTO route_templates (id, name, stops, default_timeout, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("tpl-1", "Test Route", json.dumps([{"name": "A"}, {"name": "B"}]), 60),
    )
    await db.commit()
    r = await dispatcher.dispatch(template_id="tpl-1")
    assert r["ok"] is True
    assert r["robot_id"] == "r1"
    async with db.execute("SELECT template_id FROM route_runs WHERE id = ?", (r["run_id"],)) as c:
        row = await c.fetchone()
    assert row[0] == "tpl-1"


@pytest.mark.asyncio
async def test_cancel_queued(setup):
    dispatcher, route_svc, _, _, db = setup
    await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    await dispatcher.dispatch(stops=[{"name": "B"}], default_timeout=120)
    r3 = await dispatcher.dispatch(stops=[{"name": "C"}], default_timeout=120)
    result = await dispatcher.cancel(r3["run_id"])
    assert result["ok"] is True
    async with db.execute("SELECT status FROM route_runs WHERE id = ?", (r3["run_id"],)) as c:
        row = await c.fetchone()
    assert row[0] == "cancelled"


@pytest.mark.asyncio
async def test_get_status(setup):
    dispatcher, _, _, _, _ = setup
    await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    status = dispatcher.get_status()
    assert "last_assigned" in status
    assert "queue_length" in status
    assert "active" in status


@pytest.mark.asyncio
async def test_rebuild_from_db(setup):
    dispatcher, route_svc, ws, rm, db = setup
    import json
    await db.execute(
        "INSERT INTO route_runs (id, stops, default_timeout, status, current_stop) "
        "VALUES (?, ?, ?, 'queued', -1)",
        ("run-orphan", json.dumps([{"name": "X"}]), 120),
    )
    await db.commit()
    dispatcher2 = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher2.set_route_service(route_svc)
    await dispatcher2.rebuild_from_db()
    assert "run-orphan" in dispatcher2._queue


# ── CORNER-013/028 — server restart mid-route, no zombie revival ─────


@pytest.mark.asyncio
async def test_rebuild_marks_online_running_as_interrupted(setup):
    """assigned/running rows must be marked terminal — RouteService cannot resume them."""
    dispatcher, route_svc, ws, rm, db = setup
    import json
    await db.execute(
        "INSERT INTO route_runs (id, robot_id, stops, default_timeout, status, current_stop) "
        "VALUES ('r-running', 'r1', ?, 120, 'running', 0)",
        (json.dumps([{"name": "A"}, {"name": "B"}]),),
    )
    await db.execute(
        "INSERT INTO route_runs (id, robot_id, stops, default_timeout, status, current_stop) "
        "VALUES ('r-assigned', 'r2', ?, 120, 'assigned', -1)",
        (json.dumps([{"name": "C"}]),),
    )
    await db.commit()

    dispatcher2 = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher2.set_route_service(route_svc)
    await dispatcher2.rebuild_from_db()

    async with db.execute(
        "SELECT id, status, completed_at FROM route_runs WHERE id IN ('r-running', 'r-assigned') ORDER BY id"
    ) as c:
        rows = await c.fetchall()
    statuses = {r[0]: (r[1], r[2]) for r in rows}
    assert statuses["r-running"][0] == "interrupted"
    assert statuses["r-running"][1] is not None  # completed_at filled in
    assert statuses["r-assigned"][0] == "interrupted"
    # _active is NOT repopulated with these runs — they are terminal now
    assert "r1" not in dispatcher2._active
    assert "r2" not in dispatcher2._active


@pytest.mark.asyncio
async def test_rebuild_still_marks_offline_running_as_completed(setup):
    """offline_running cleanup is the existing behaviour and must still work."""
    dispatcher, route_svc, ws, rm, db = setup
    import json
    await db.execute(
        "INSERT INTO route_runs (id, robot_id, stops, default_timeout, status, current_stop, execution_mode) "
        "VALUES ('r-off', 'r1', ?, 120, 'offline_running', 0, 'offline')",
        (json.dumps([{"name": "A"}]),),
    )
    await db.commit()

    dispatcher2 = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher2.set_route_service(route_svc)
    await dispatcher2.rebuild_from_db()

    async with db.execute("SELECT status FROM route_runs WHERE id = 'r-off'") as c:
        row = await c.fetchone()
    assert row[0] == "completed"
