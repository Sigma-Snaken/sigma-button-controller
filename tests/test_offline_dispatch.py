import pytest
import pytest_asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.route_dispatcher import RouteDispatcher


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


class FakeRobotEntry:
    def __init__(self, ip):
        self.ip = ip


class FakeRobotManager:
    def __init__(self):
        self._robots = {"r1": FakeRobotEntry("192.168.50.133")}

    def all_ids(self):
        return list(self._robots.keys())

    def get(self, robot_id):
        return self._robots.get(robot_id)


class FakeDeployer:
    def __init__(self):
        self.calls = []

    async def deploy(self, robot_ip, script, run_id):
        self.calls.append({"robot_ip": robot_ip, "script": script, "run_id": run_id})
        return {"ok": True}


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, run_id, stops, shelf_name, default_timeout, pi_url):
        self.calls.append({
            "run_id": run_id,
            "stops": stops,
            "shelf_name": shelf_name,
            "default_timeout": default_timeout,
            "pi_url": pi_url,
        })
        return "print('hello')"


class FakeRouteService:
    def __init__(self):
        self.started = []

    async def start_run(self, run_id: str, robot_id: str):
        self.started.append((run_id, robot_id))


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
    generator = FakeGenerator()
    deployer = FakeDeployer()
    route_svc = FakeRouteService()

    dispatcher = RouteDispatcher(db=db, ws_manager=ws, robot_manager=rm)
    dispatcher.set_route_service(route_svc)
    dispatcher.set_offline_components(generator, deployer)
    dispatcher.set_route_mode("offline")
    dispatcher.set_pi_url("http://localhost:8000")

    yield dispatcher, generator, deployer, route_svc, ws, db
    await disconnect()


@pytest.mark.asyncio
async def test_offline_dispatch_generates_and_deploys(setup):
    dispatcher, generator, deployer, route_svc, ws, db = setup
    stops = [{"name": "A"}, {"name": "B"}]
    result = await dispatcher.dispatch(stops=stops, default_timeout=60, shelf_name="shelf-1")

    assert result["ok"] is True
    assert result["status"] == "offline_running"
    assert result["robot_id"] == "r1"

    # Generator was called with correct args
    assert len(generator.calls) == 1
    gen_call = generator.calls[0]
    assert gen_call["stops"] == stops
    assert gen_call["shelf_name"] == "shelf-1"
    assert gen_call["default_timeout"] == 60
    assert gen_call["pi_url"] == "http://localhost:8000"
    assert gen_call["run_id"] == result["run_id"]

    # Deployer was called with robot IP and script
    assert len(deployer.calls) == 1
    dep_call = deployer.calls[0]
    assert dep_call["robot_ip"] == "192.168.50.133"
    assert dep_call["script"] == "print('hello')"
    assert dep_call["run_id"] == result["run_id"]

    # WS broadcast
    events = [e[0] for e in ws.events]
    assert "route:offline_started" in events


@pytest.mark.asyncio
async def test_offline_dispatch_records_execution_mode(setup):
    dispatcher, generator, deployer, route_svc, ws, db = setup
    result = await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)

    assert result["ok"] is True
    async with db.execute(
        "SELECT status, execution_mode FROM route_runs WHERE id = ?",
        (result["run_id"],),
    ) as cursor:
        row = await cursor.fetchone()

    assert row[0] == "offline_running"
    assert row[1] == "offline"


@pytest.mark.asyncio
async def test_offline_dispatch_does_not_start_route_service(setup):
    dispatcher, generator, deployer, route_svc, ws, db = setup
    await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    assert route_svc.started == []


@pytest.mark.asyncio
async def test_online_dispatch_uses_route_service(setup):
    dispatcher, generator, deployer, route_svc, ws, db = setup
    # Switch to online mode
    dispatcher.set_route_mode("online")

    result = await dispatcher.dispatch(stops=[{"name": "A"}], default_timeout=120)
    assert result["ok"] is True
    assert result["status"] == "assigned"

    # route_service.start_run was called
    assert len(route_svc.started) == 1
    assert route_svc.started[0][1] == "r1"

    # deployer was NOT called
    assert deployer.calls == []
