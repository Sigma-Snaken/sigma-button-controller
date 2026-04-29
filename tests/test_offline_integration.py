"""End-to-end: dispatch offline route → deploy → receive reports → complete."""
import pytest
import pytest_asyncio
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

# Import main first to initialize _state before routers.routes is imported
import main  # noqa: F401

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.route_dispatcher import RouteDispatcher
from services.offline_route_generator import OfflineRouteGenerator
from routers.routes import _handle_offline_report


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


class FakeRobotManager:
    def __init__(self):
        self._robots = {"r1": type("R", (), {"ip": "192.168.50.133"})()}

    def all_ids(self):
        return list(self._robots.keys())

    def get(self, robot_id):
        return self._robots.get(robot_id)


class FakeDeployer:
    def __init__(self):
        self.calls = []
        self.scripts = []

    async def deploy(self, robot_ip, script_content, run_id):
        self.calls.append((robot_ip, run_id))
        self.scripts.append(script_content)
        return {"ok": True, "run_id": run_id, "robot_ip": robot_ip}


@pytest_asyncio.fixture
async def setup(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot A", "192.168.50.133"),
    )
    await db.commit()

    ws = FakeWSManager()
    rm = FakeRobotManager()
    deployer = FakeDeployer()
    generator = OfflineRouteGenerator()

    dispatcher = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher.set_offline_components(generator, deployer)
    dispatcher.set_route_mode("offline")
    dispatcher.set_pi_url("http://192.168.50.6:8000")

    yield dispatcher, deployer, generator, ws, db

    await disconnect()


@pytest.mark.asyncio
async def test_offline_full_lifecycle(setup):
    """Dispatch offline route, verify script generated, simulate reports, verify DB."""
    dispatcher, deployer, generator, ws, db = setup

    # Dispatch
    result = await dispatcher.dispatch(
        stops=[{"name": "StationA"}, {"name": "StationB"}],
        default_timeout=60,
        shelf_name="s1",
    )
    assert result["ok"] is True
    assert result["status"] == "offline_running"
    run_id = result["run_id"]

    # Verify script was generated with correct content
    assert len(deployer.scripts) == 1
    script = deployer.scripts[0]
    assert "StationA" in script
    assert "StationB" in script
    assert "s1" in script
    assert "192.168.50.6:8000" in script
    compile(script, "<test>", "exec")  # valid Python

    # Verify DB state
    async with db.execute(
        "SELECT status, execution_mode, robot_id FROM route_runs WHERE id = ?", (run_id,)
    ) as c:
        row = await c.fetchone()
    assert row[0] == "offline_running"
    assert row[1] == "offline"
    assert row[2] == "r1"

    # Simulate reports coming back from robot
    await _handle_offline_report(db, ws, run_id, "moving", 0, "2026-04-08T14:00:00")
    await _handle_offline_report(db, ws, run_id, "arrived", 0, "2026-04-08T14:01:00")
    await _handle_offline_report(db, ws, run_id, "shake_confirmed", 0, "2026-04-08T14:02:00")
    await _handle_offline_report(db, ws, run_id, "moving", 1, "2026-04-08T14:03:00")
    await _handle_offline_report(db, ws, run_id, "arrived", 1, "2026-04-08T14:04:00")
    await _handle_offline_report(db, ws, run_id, "timeout", 1, "2026-04-08T14:06:00")
    await _handle_offline_report(db, ws, run_id, "completed", None, "2026-04-08T14:10:00")

    # Verify final DB state
    async with db.execute(
        "SELECT status, completed_at FROM route_runs WHERE id = ?", (run_id,)
    ) as c:
        row = await c.fetchone()
    assert row[0] == "completed"
    assert row[1] is not None

    # Verify stop logs
    async with db.execute(
        "SELECT stop_index, confirmed_by, timed_out FROM route_stop_logs WHERE run_id = ? ORDER BY stop_index",
        (run_id,),
    ) as c:
        logs = await c.fetchall()
    assert len(logs) == 2
    assert logs[0][1] == "imu_shake"   # stop 0 confirmed by shake
    assert logs[0][2] == 0             # stop 0 not timed out
    assert logs[1][1] is None          # stop 1 not confirmed
    assert logs[1][2] == 1             # stop 1 timed out

    # Verify WS events were broadcast
    event_types = [e[0] for e in ws.events]
    assert "route:offline_started" in event_types
    assert "route:offline_report" in event_types


@pytest.mark.asyncio
async def test_offline_deploy_failure_marks_failed(setup):
    """If SSH deploy fails, route should be marked as failed."""
    dispatcher, deployer, generator, ws, db = setup

    # Make deployer fail
    async def fail_deploy(robot_ip, script, run_id):
        return {"ok": False, "error": "Connection refused"}

    deployer.deploy = fail_deploy

    result = await dispatcher.dispatch(
        stops=[{"name": "A"}],
        default_timeout=60,
        shelf_name="s1",
    )
    assert result["ok"] is False
    assert "Connection refused" in result["error"]
