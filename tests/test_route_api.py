import pytest
import pytest_asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from httpx import AsyncClient, ASGITransport
from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations


class FakeRouteDispatcher:
    def __init__(self):
        self.dispatch_calls = []
        self.cancel_calls = []

    async def dispatch(self, **kwargs):
        self.dispatch_calls.append(kwargs)
        return {"ok": True, "run_id": "run-1", "robot_id": "r1", "status": "assigned"}

    async def cancel(self, run_id):
        self.cancel_calls.append(run_id)
        return {"ok": True}

    def get_status(self):
        return {"last_assigned": "r1", "queue_length": 0, "queue": [], "active": {}}


class FakeRouteService:
    def get_active_runs(self):
        return {}


class FakeWSManager:
    async def broadcast(self, event, data):
        pass


class FakeRobotManager:
    def all_ids(self):
        return ["r1"]
    def get(self, robot_id):
        return None


@pytest_asyncio.fixture
async def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)

    from main import app, _state
    _state.update({
        "db": db,
        "route_dispatcher": FakeRouteDispatcher(),
        "route_service": FakeRouteService(),
        "ws_manager": FakeWSManager(),
        "robot_manager": FakeRobotManager(),
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db, _state
    await disconnect()


@pytest.mark.asyncio
async def test_create_template(client):
    c, db, _ = client
    resp = await c.post("/api/routes/templates", json={
        "name": "Test Route", "stops": [{"name": "A"}, {"name": "B"}], "default_timeout": 120,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["ok"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_list_templates(client):
    c, db, _ = client
    await c.post("/api/routes/templates", json={"name": "R1", "stops": [{"name": "A"}], "default_timeout": 60})
    resp = await c.get("/api/routes/templates")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_update_template(client):
    c, db, _ = client
    create = await c.post("/api/routes/templates", json={"name": "Old", "stops": [{"name": "A"}], "default_timeout": 60})
    tid = create.json()["id"]
    resp = await c.put(f"/api/routes/templates/{tid}", json={"name": "New", "stops": [{"name": "A"}, {"name": "B"}], "default_timeout": 90})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_template(client):
    c, db, _ = client
    create = await c.post("/api/routes/templates", json={"name": "Del", "stops": [{"name": "A"}], "default_timeout": 60})
    tid = create.json()["id"]
    resp = await c.delete(f"/api/routes/templates/{tid}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dispatch_adhoc(client):
    c, _, state = client
    resp = await c.post("/api/routes/dispatch", json={"stops": [{"name": "A"}], "default_timeout": 120})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_dispatch_from_template(client):
    c, _, state = client
    resp = await c.post("/api/routes/dispatch", json={"template_id": "tpl-1"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_run(client):
    c, _, state = client
    resp = await c.post("/api/routes/runs/run-1/cancel")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_dispatcher_status(client):
    c, _, _ = client
    resp = await c.get("/api/routes/dispatcher/status")
    assert resp.status_code == 200
    assert "last_assigned" in resp.json()


@pytest.mark.asyncio
async def test_history(client):
    c, db, _ = client
    await db.execute(
        "INSERT INTO route_runs (id, stops, default_timeout, status, current_stop, completed_at) "
        "VALUES (?, ?, ?, 'completed', 1, datetime('now'))",
        ("hist-1", json.dumps([{"name": "A"}]), 60),
    )
    await db.commit()
    resp = await c.get("/api/routes/history")
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) >= 1
