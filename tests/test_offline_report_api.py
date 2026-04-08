import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

# Import main first to initialize _state before routers.routes is imported
import main  # noqa: F401

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from routers.routes import _handle_offline_report


class FakeWS:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot A", "1.2.3.4"),
    )
    await db.execute(
        "INSERT INTO route_runs (id, robot_id, stops, default_timeout, shelf_name, "
        "status, current_stop, execution_mode, started_at) "
        "VALUES ('run-1', 'r1', '[{\"name\":\"A\"}]', 120, 's1', 'offline_running', -1, 'offline', datetime('now'))"
    )
    await db.commit()
    yield db
    await disconnect()


@pytest.mark.asyncio
async def test_report_moving_updates_current_stop(db):
    ws = FakeWS()
    result = await _handle_offline_report(db, ws, "run-1", "moving", 0, None)
    assert result == {"ok": True}

    async with db.execute(
        "SELECT current_stop, status FROM route_runs WHERE id = 'run-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row[0] == 0
    assert row[1] == "offline_running"


@pytest.mark.asyncio
async def test_report_arrived_creates_stop_log(db):
    ws = FakeWS()
    result = await _handle_offline_report(db, ws, "run-1", "arrived", 0, None)
    assert result == {"ok": True}

    async with db.execute(
        "SELECT stop_index, location_name FROM route_stop_logs WHERE run_id = 'run-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0
    assert row[1] == "A"


@pytest.mark.asyncio
async def test_report_completed_updates_status(db):
    ws = FakeWS()
    result = await _handle_offline_report(db, ws, "run-1", "completed", None, None)
    assert result == {"ok": True}

    async with db.execute(
        "SELECT status, completed_at FROM route_runs WHERE id = 'run-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row[0] == "completed"
    assert row[1] is not None


@pytest.mark.asyncio
async def test_report_failed_updates_status(db):
    ws = FakeWS()
    result = await _handle_offline_report(db, ws, "run-1", "failed", None, None)
    assert result == {"ok": True}

    async with db.execute(
        "SELECT status, completed_at FROM route_runs WHERE id = 'run-1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row[0] == "failed"
    assert row[1] is not None


@pytest.mark.asyncio
async def test_report_broadcasts_ws_event(db):
    ws = FakeWS()
    await _handle_offline_report(db, ws, "run-1", "moving", 0, None)
    assert len(ws.events) == 1
    event_name, data = ws.events[0]
    assert event_name == "route:offline_report"
    assert data["run_id"] == "run-1"
    assert data["event"] == "moving"


@pytest.mark.asyncio
async def test_report_run_not_found(db):
    ws = FakeWS()
    result = await _handle_offline_report(db, ws, "nonexistent-run", "moving", 0, None)
    assert result == {"ok": False, "error": "Run not found"}
