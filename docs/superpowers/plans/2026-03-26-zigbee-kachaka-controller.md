# Zigbee Button → Kachaka Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Pi 5 app where Zigbee buttons (SNZB-01) trigger Kachaka robot actions, with a web UI for pairing and configuration.

**Architecture:** FastAPI backend with MQTT subscription (aiomqtt) for Zigbee2MQTT button events, SQLite for bindings storage, kachaka-sdk-toolkit for robot control. Vanilla JS SPA frontend with 4 tabs (robots, buttons, bindings, logs). Docker Compose with 3 containers (Mosquitto, Zigbee2MQTT, App).

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, aiomqtt, kachaka-sdk-toolkit, Vanilla JS, Docker Compose, GitHub Actions CI

---

## File Map

### Backend (`src/backend/`)

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI app + lifespan (startup/shutdown orchestration) |
| `database/connection.py` | aiosqlite connection, WAL mode, singleton |
| `database/migrations.py` | Versioned schema migrations (robots, buttons, bindings, action_logs) |
| `services/ws_manager.py` | WebSocket connection pool + broadcast |
| `services/robot_manager.py` | Multi-robot lifecycle (dict[id → RobotService]), kachaka_core wrappers |
| `services/action_executor.py` | ACTION_MAP dispatch: action string → KachakaCommands call |
| `services/mqtt_service.py` | aiomqtt connection, subscribe zigbee2mqtt/#, message routing |
| `services/button_manager.py` | Pairing flow, binding lookup, action dispatch, logging |
| `routers/robots.py` | CRUD /api/robots + /locations + /shortcuts |
| `routers/buttons.py` | CRUD /api/buttons + pair/stop endpoints |
| `routers/bindings.py` | GET/PUT /api/bindings/{button_id} |
| `routers/logs.py` | GET /api/logs (paginated) |
| `routers/ws.py` | WebSocket /ws endpoint |
| `utils/logger.py` | Unified logging config |

### Frontend (`src/frontend/`)

| File | Responsibility |
|------|---------------|
| `index.html` | SPA shell with tab navigation |
| `css/style.css` | Styles |
| `js/app.js` | Tab router + init |
| `js/api.js` | REST API wrapper (fetch helpers) |
| `js/websocket.js` | WebSocket connection + event dispatch |
| `js/robots.js` | Robot management tab |
| `js/buttons.js` | Button pairing tab |
| `js/bindings.js` | Binding configuration tab |
| `js/logs.js` | Execution log tab |

### Infrastructure

| File | Responsibility |
|------|---------------|
| `requirements.txt` | Python dependencies |
| `Dockerfile` | App container image (uv, python:3.12-slim) |
| `docker-compose.yml` | Dev: local build + 3 containers |
| `docker-compose.override.yml` | Dev: volume mount src/ + --reload |
| `mosquitto/mosquitto.conf` | Mosquitto broker config |
| `zigbee2mqtt/configuration.yaml` | Z2M config (MQTT + serial port) |
| `deploy/docker-compose.yml` | Prod: pull from GHCR |
| `deploy/.env.example` | Prod env vars template |
| `deploy/daemon.json` | Docker daemon IPv4 enforcement |
| `deploy/setup.sh` | First-time Pi setup script |
| `.github/workflows/build.yml` | CI: cross-compile + push GHCR |
| `.env.example` | Dev env vars template |
| `.gitignore` | Ignore data/, .superpowers/, docs/plans/ |

---

## Task 1: Project Scaffolding + Database

**Files:**
- Create: `requirements.txt`
- Create: `src/backend/database/connection.py`
- Create: `src/backend/database/migrations.py`
- Create: `src/backend/utils/logger.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Create requirements.txt**

```
kachaka-sdk-toolkit
fastapi
uvicorn[standard]
aiosqlite
aiomqtt
pytest
pytest-asyncio
```

- [ ] **Step 2: Create virtual environment and install dependencies**

Run:
```bash
cd /home/snaken/CodeBase/pi-zigbee
uv venv .venv && uv pip install -r requirements.txt
```

- [ ] **Step 3: Create logger utility**

Create `src/backend/utils/__init__.py` (empty) and `src/backend/utils/logger.py`:

```python
import logging
import sys


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
```

- [ ] **Step 4: Write failing database tests**

Create `src/backend/database/__init__.py` (empty) and `tests/test_database.py`:

```python
import pytest
import pytest_asyncio
import aiosqlite
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import get_db, connect, disconnect
from database.migrations import run_migrations


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    yield db
    await disconnect()


@pytest.mark.asyncio
async def test_migrations_create_tables(db):
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cursor:
        tables = [row[0] for row in await cursor.fetchall()]
    assert "robots" in tables
    assert "buttons" in tables
    assert "bindings" in tables
    assert "action_logs" in tables


@pytest.mark.asyncio
async def test_migrations_idempotent(db):
    """Running migrations twice should not fail."""
    await run_migrations(db)
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cursor:
        tables = [row[0] for row in await cursor.fetchall()]
    assert "robots" in tables


@pytest.mark.asyncio
async def test_insert_robot(db):
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        ("kachaka-1", "大廳機器人", "192.168.50.101", True),
    )
    await db.commit()
    async with db.execute("SELECT id, name, ip FROM robots") as cursor:
        row = await cursor.fetchone()
    assert row == ("kachaka-1", "大廳機器人", "192.168.50.101")


@pytest.mark.asyncio
async def test_binding_unique_constraint(db):
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        ("r1", "Robot", "1.2.3.4", True),
    )
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00aaaaaa", "Button A"),
    )
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
        "VALUES (1, 'single', 'r1', 'return_home', '{}', 1, datetime('now'))"
    )
    await db.commit()
    with pytest.raises(Exception):
        await db.execute(
            "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
            "VALUES (1, 'single', 'r1', 'speak', '{\"text\":\"hi\"}', 1, datetime('now'))"
        )
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_database.py -v`
Expected: ImportError or ModuleNotFoundError

- [ ] **Step 6: Implement database connection**

Create `src/backend/database/connection.py`:

```python
import aiosqlite

_db: aiosqlite.Connection | None = None
_db_path: str = "data/app.db"


async def connect(db_path: str | None = None) -> None:
    global _db, _db_path
    if db_path:
        _db_path = db_path
    _db = await aiosqlite.connect(_db_path)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.execute("PRAGMA foreign_keys=ON")


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not connected. Call connect() first.")
    return _db


async def disconnect() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
```

- [ ] **Step 7: Implement migrations**

Create `src/backend/database/migrations.py`:

```python
import aiosqlite

MIGRATIONS = [
    # V1: Initial schema
    """
    CREATE TABLE IF NOT EXISTS robots (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        ip TEXT NOT NULL,
        enabled BOOLEAN DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ieee_addr TEXT UNIQUE NOT NULL,
        name TEXT,
        paired_at TEXT NOT NULL,
        battery INTEGER,
        last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS bindings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        button_id INTEGER NOT NULL REFERENCES buttons(id) ON DELETE CASCADE,
        trigger TEXT NOT NULL CHECK(trigger IN ('single', 'double', 'long')),
        robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
        action TEXT NOT NULL,
        params TEXT DEFAULT '{}',
        enabled BOOLEAN DEFAULT 1,
        created_at TEXT,
        UNIQUE(button_id, trigger)
    );
    CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        button_id INTEGER,
        trigger TEXT,
        robot_id TEXT,
        action TEXT,
        params TEXT,
        result_ok BOOLEAN,
        result_detail TEXT,
        executed_at TEXT NOT NULL
    );
    """,
]


async def run_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY)"
    )
    async with db.execute("SELECT COALESCE(MAX(version), 0) FROM _migrations") as cursor:
        current = (await cursor.fetchone())[0]
    for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                await db.execute(statement)
        await db.execute("INSERT INTO _migrations (version) VALUES (?)", (i,))
    await db.commit()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_database.py -v`
Expected: All 4 tests PASS

- [ ] **Step 9: Commit**

```bash
git add requirements.txt src/backend/utils/ src/backend/database/ tests/test_database.py
git commit -m "feat: add database layer with versioned migrations"
```

---

## Task 2: WebSocket Manager

**Files:**
- Create: `src/backend/services/__init__.py`
- Create: `src/backend/services/ws_manager.py`
- Create: `tests/test_ws_manager.py`

- [ ] **Step 1: Write failing tests**

Create `src/backend/services/__init__.py` (empty) and `tests/test_ws_manager.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_ws_manager.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement WSManager**

Create `src/backend/services/ws_manager.py`:

```python
import json
from fastapi import WebSocket

from utils.logger import get_logger

logger = get_logger("ws_manager")


class WSManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info(f"WebSocket connected. Total: {len(self._connections)}")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info(f"WebSocket disconnected. Total: {len(self._connections)}")

    async def broadcast(self, event: str, data: dict) -> None:
        message = json.dumps({"event": event, "data": data})
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_ws_manager.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/services/ tests/test_ws_manager.py
git commit -m "feat: add WebSocket manager for real-time event broadcasting"
```

---

## Task 3: Robot Manager

**Files:**
- Create: `src/backend/services/robot_manager.py`
- Create: `tests/test_robot_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_robot_manager.py`:

```python
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.robot_manager import RobotService, RobotManager


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip

    def ping(self):
        return {"ok": True, "serial": "KCK-TEST", "pose": {"x": 0, "y": 0, "theta": 0}}


class FakeCommands:
    def __init__(self, conn):
        self.conn = conn

    def move_to_location(self, name):
        return {"ok": True, "action": "move_to_location", "target": name}

    def return_home(self):
        return {"ok": True, "action": "return_home"}

    def speak(self, text):
        return {"ok": True, "action": "speak"}


class FakeQueries:
    def __init__(self, conn):
        self.conn = conn

    def list_locations(self):
        return {"ok": True, "locations": [{"name": "Kitchen", "id": "loc1"}]}

    def get_battery(self):
        return {"ok": True, "percentage": 85}


def test_robot_service_init():
    svc = RobotService("test-1", "1.2.3.4")
    assert svc.robot_id == "test-1"
    assert svc.ip == "1.2.3.4"


def test_robot_manager_add_remove():
    mgr = RobotManager()
    mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
            commands_cls=FakeCommands, queries_cls=FakeQueries)
    assert mgr.get("r1") is not None
    assert "r1" in mgr.all_ids()
    mgr.remove("r1")
    assert mgr.get("r1") is None


def test_robot_manager_get_nonexistent():
    mgr = RobotManager()
    assert mgr.get("nonexistent") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_robot_manager.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement RobotManager**

Create `src/backend/services/robot_manager.py`:

```python
from kachaka_core.connection import KachakaConnection
from kachaka_core.commands import KachakaCommands
from kachaka_core.queries import KachakaQueries

from utils.logger import get_logger

logger = get_logger("robot_manager")


class RobotService:
    """Wraps kachaka_core components for a single robot."""

    def __init__(self, robot_id: str, ip: str):
        self.robot_id = robot_id
        self.ip = ip
        self.conn = None
        self.commands: KachakaCommands | None = None
        self.queries: KachakaQueries | None = None

    def connect(self, connect_fn=None, commands_cls=None, queries_cls=None) -> dict:
        _connect = connect_fn or KachakaConnection.get
        _cmds_cls = commands_cls or KachakaCommands
        _queries_cls = queries_cls or KachakaQueries
        self.conn = _connect(self.ip)
        self.commands = _cmds_cls(self.conn)
        self.queries = _queries_cls(self.conn)
        result = self.conn.ping()
        logger.info(f"Connected to robot {self.robot_id} at {self.ip}: {result.get('serial', 'unknown')}")
        return result

    def stop(self) -> None:
        logger.info(f"Stopped robot service for {self.robot_id}")


class RobotManager:
    """Manages multiple robot connections."""

    def __init__(self):
        self._robots: dict[str, RobotService] = {}

    def add(self, robot_id: str, ip: str, **kwargs) -> RobotService:
        svc = RobotService(robot_id, ip)
        svc.connect(**kwargs)
        self._robots[robot_id] = svc
        return svc

    def remove(self, robot_id: str) -> None:
        svc = self._robots.pop(robot_id, None)
        if svc:
            svc.stop()

    def get(self, robot_id: str) -> RobotService | None:
        return self._robots.get(robot_id)

    def all_ids(self) -> list[str]:
        return list(self._robots.keys())

    def stop_all(self) -> None:
        for svc in self._robots.values():
            svc.stop()
        self._robots.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_robot_manager.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/services/robot_manager.py tests/test_robot_manager.py
git commit -m "feat: add RobotManager with kachaka_core integration"
```

---

## Task 4: Action Executor

**Files:**
- Create: `src/backend/services/action_executor.py`
- Create: `tests/test_action_executor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_action_executor.py`:

```python
import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.action_executor import ActionExecutor
from services.robot_manager import RobotManager


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip

    def ping(self):
        return {"ok": True, "serial": "KCK-TEST"}


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


class FakeQueries:
    def __init__(self, conn):
        pass


@pytest.fixture
def executor():
    mgr = RobotManager()
    mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
            commands_cls=FakeCommands, queries_cls=FakeQueries)
    return ActionExecutor(mgr)


def test_move_to_location(executor):
    result = executor.execute("r1", "move_to_location", {"name": "Kitchen"})
    assert result["ok"] is True


def test_return_home(executor):
    result = executor.execute("r1", "return_home", {})
    assert result["ok"] is True


def test_speak(executor):
    result = executor.execute("r1", "speak", {"text": "你好"})
    assert result["ok"] is True


def test_start_shortcut(executor):
    result = executor.execute("r1", "start_shortcut", {"shortcut_id": "sc-1"})
    assert result["ok"] is True


def test_unknown_action(executor):
    result = executor.execute("r1", "fly_away", {})
    assert result["ok"] is False
    assert "Unknown action" in result["error"]


def test_unknown_robot(executor):
    result = executor.execute("nonexistent", "return_home", {})
    assert result["ok"] is False
    assert "not found" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_action_executor.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement ActionExecutor**

Create `src/backend/services/action_executor.py`:

```python
from services.robot_manager import RobotManager
from utils.logger import get_logger

logger = get_logger("action_executor")


class ActionExecutor:
    def __init__(self, robot_manager: RobotManager):
        self._robot_manager = robot_manager

    def execute(self, robot_id: str, action: str, params: dict) -> dict:
        svc = self._robot_manager.get(robot_id)
        if not svc:
            return {"ok": False, "error": f"Robot '{robot_id}' not found"}
        if not svc.commands:
            return {"ok": False, "error": f"Robot '{robot_id}' not connected"}

        cmds = svc.commands
        action_map = {
            "move_to_location": lambda: cmds.move_to_location(params["name"]),
            "return_home": lambda: cmds.return_home(),
            "speak": lambda: cmds.speak(params["text"]),
            "move_shelf": lambda: cmds.move_shelf(params["shelf"], params["location"]),
            "return_shelf": lambda: cmds.return_shelf(params.get("shelf")),
            "dock_shelf": lambda: cmds.dock_shelf(),
            "undock_shelf": lambda: cmds.undock_shelf(),
            "start_shortcut": lambda: cmds.start_shortcut(params["shortcut_id"]),
        }

        handler = action_map.get(action)
        if not handler:
            return {"ok": False, "error": f"Unknown action: {action}"}

        try:
            result = handler()
            logger.info(f"Executed {action} on {robot_id}: ok={result.get('ok')}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute {action} on {robot_id}: {e}")
            return {"ok": False, "error": str(e)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_action_executor.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/services/action_executor.py tests/test_action_executor.py
git commit -m "feat: add ActionExecutor with action → KachakaCommands dispatch"
```

---

## Task 5: MQTT Service

**Files:**
- Create: `src/backend/services/mqtt_service.py`
- Create: `tests/test_mqtt_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_mqtt_service.py`:

```python
import pytest
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from services.mqtt_service import parse_zigbee_message


def test_parse_button_action():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "single", "battery": 95, "linkquality": 120})
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "button_action"
    assert result["ieee_addr"] == "0x00124b00abcdef"
    assert result["action"] == "single"


def test_parse_button_action_double():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "double"})
    result = parse_zigbee_message(topic, payload)
    assert result["action"] == "double"


def test_parse_button_action_long():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "long"})
    result = parse_zigbee_message(topic, payload)
    assert result["action"] == "long"


def test_parse_empty_action_ignored():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"action": "", "battery": 95})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_device_joined():
    topic = "zigbee2mqtt/bridge/event"
    payload = json.dumps({
        "type": "device_joined",
        "data": {"friendly_name": "0x00124b00ffffff", "ieee_address": "0x00124b00ffffff"}
    })
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "device_joined"
    assert result["ieee_addr"] == "0x00124b00ffffff"


def test_parse_bridge_state_ignored():
    topic = "zigbee2mqtt/bridge/state"
    payload = json.dumps({"state": "online"})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_non_action_device_message_ignored():
    topic = "zigbee2mqtt/0x00124b00abcdef"
    payload = json.dumps({"battery": 95, "linkquality": 120})
    result = parse_zigbee_message(topic, payload)
    assert result is None


def test_parse_device_announce():
    topic = "zigbee2mqtt/bridge/event"
    payload = json.dumps({
        "type": "device_announce",
        "data": {"friendly_name": "0x00124b00abcdef", "ieee_address": "0x00124b00abcdef"}
    })
    result = parse_zigbee_message(topic, payload)
    assert result is not None
    assert result["type"] == "device_announce"
    assert result["ieee_addr"] == "0x00124b00abcdef"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_mqtt_service.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement MQTTService**

Create `src/backend/services/mqtt_service.py`:

```python
import asyncio
import json
from typing import Callable, Awaitable

import aiomqtt

from utils.logger import get_logger

logger = get_logger("mqtt_service")


def parse_zigbee_message(topic: str, payload: str) -> dict | None:
    """Parse a Zigbee2MQTT message into a structured event or None if irrelevant."""
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != "zigbee2mqtt":
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    # Bridge events (device_joined, device_announce, etc.)
    if len(parts) >= 3 and parts[1] == "bridge" and parts[2] == "event":
        event_type = data.get("type", "")
        event_data = data.get("data", {})
        if event_type in ("device_joined", "device_announce"):
            ieee = event_data.get("ieee_address", "")
            if ieee:
                return {
                    "type": event_type,
                    "ieee_addr": ieee,
                    "friendly_name": event_data.get("friendly_name", ieee),
                }
        return None

    # Other bridge topics — ignore
    if len(parts) >= 2 and parts[1] == "bridge":
        return None

    # Device messages (button actions)
    ieee_addr = parts[1]
    action = data.get("action")
    if action:
        return {
            "type": "button_action",
            "ieee_addr": ieee_addr,
            "action": action,
            "battery": data.get("battery"),
            "linkquality": data.get("linkquality"),
        }

    return None


class MQTTService:
    def __init__(self, host: str = "localhost", port: int = 1883):
        self._host = host
        self._port = port
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._on_message: Callable[[dict], Awaitable[None]] | None = None

    def set_handler(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._on_message = handler

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())
        logger.info(f"MQTT service started, connecting to {self._host}:{self._port}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT service stopped")

    async def publish(self, topic: str, payload: dict) -> None:
        if self._client:
            await self._client.publish(topic, json.dumps(payload))

    async def permit_join(self, enable: bool, time: int = 120) -> None:
        await self.publish(
            "zigbee2mqtt/bridge/request/permit_join",
            {"value": enable, "time": time},
        )
        logger.info(f"permit_join={'enabled' if enable else 'disabled'}, time={time}s")

    async def _listen(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(self._host, self._port) as client:
                    self._client = client
                    await client.subscribe("zigbee2mqtt/#")
                    logger.info("Subscribed to zigbee2mqtt/#")
                    async for message in client.messages:
                        topic = str(message.topic)
                        payload = message.payload.decode() if message.payload else ""
                        parsed = parse_zigbee_message(topic, payload)
                        if parsed and self._on_message:
                            try:
                                await self._on_message(parsed)
                            except Exception as e:
                                logger.error(f"Handler error: {e}")
            except aiomqtt.MqttError as e:
                logger.warning(f"MQTT connection lost: {e}. Reconnecting in 5s...")
                self._client = None
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                self._client = None
                raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_mqtt_service.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/services/mqtt_service.py tests/test_mqtt_service.py
git commit -m "feat: add MQTT service with Zigbee2MQTT message parsing"
```

---

## Task 6: Button Manager

**Files:**
- Create: `src/backend/services/button_manager.py`
- Create: `tests/test_button_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_button_manager.py`:

```python
import pytest
import pytest_asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.button_manager import ButtonManager
from services.ws_manager import WSManager


class FakeActionExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, robot_id, action, params):
        self.calls.append((robot_id, action, params))
        return {"ok": True, "action": action}


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


@pytest_asyncio.fixture
async def setup(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    executor = FakeActionExecutor()
    ws = FakeWSManager()
    mgr = ButtonManager(db, executor, ws)
    yield mgr, db, executor, ws
    await disconnect()


@pytest.mark.asyncio
async def test_handle_device_joined(setup):
    mgr, db, _, ws = setup
    await mgr.handle_message({
        "type": "device_joined",
        "ieee_addr": "0x00124b00aaaaaa",
        "friendly_name": "0x00124b00aaaaaa",
    })
    async with db.execute("SELECT ieee_addr FROM buttons") as cursor:
        rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "0x00124b00aaaaaa"
    assert any(e[0] == "device_paired" for e in ws.events)


@pytest.mark.asyncio
async def test_handle_device_joined_duplicate(setup):
    mgr, db, _, _ = setup
    msg = {"type": "device_joined", "ieee_addr": "0x00124b00bbbbbb", "friendly_name": "test"}
    await mgr.handle_message(msg)
    await mgr.handle_message(msg)  # duplicate
    async with db.execute("SELECT COUNT(*) FROM buttons") as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 1


@pytest.mark.asyncio
async def test_handle_button_action_with_binding(setup):
    mgr, db, executor, ws = setup
    # Setup: robot + button + binding
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot", "1.2.3.4"),
    )
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00cccccc", "Test Button"),
    )
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
        "VALUES (1, 'single', 'r1', 'return_home', '{}', 1, datetime('now'))"
    )
    await db.commit()

    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00cccccc",
        "action": "single",
    })
    assert len(executor.calls) == 1
    assert executor.calls[0] == ("r1", "return_home", {})
    # Check action_logs
    async with db.execute("SELECT action, result_ok FROM action_logs") as cursor:
        row = await cursor.fetchone()
    assert row[0] == "return_home"
    assert row[1] == 1


@pytest.mark.asyncio
async def test_handle_button_action_no_binding(setup):
    mgr, db, executor, _ = setup
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00dddddd", "Unbound"),
    )
    await db.commit()
    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00dddddd",
        "action": "single",
    })
    assert len(executor.calls) == 0


@pytest.mark.asyncio
async def test_handle_button_action_unknown_button(setup):
    mgr, _, executor, _ = setup
    await mgr.handle_message({
        "type": "button_action",
        "ieee_addr": "0x00124b00unknown",
        "action": "single",
    })
    assert len(executor.calls) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_button_manager.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement ButtonManager**

Create `src/backend/services/button_manager.py`:

```python
import json
from datetime import datetime, timezone

import aiosqlite

from services.action_executor import ActionExecutor
from services.ws_manager import WSManager
from utils.logger import get_logger

logger = get_logger("button_manager")


class ButtonManager:
    def __init__(
        self,
        db: aiosqlite.Connection,
        action_executor: ActionExecutor,
        ws_manager: WSManager,
    ):
        self._db = db
        self._executor = action_executor
        self._ws = ws_manager

    async def handle_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "device_joined":
            await self._on_device_joined(msg)
        elif msg_type == "device_announce":
            await self._on_device_announce(msg)
        elif msg_type == "button_action":
            await self._on_button_action(msg)

    async def _on_device_joined(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        # Check if already exists
        async with self._db.execute(
            "SELECT id FROM buttons WHERE ieee_addr = ?", (ieee,)
        ) as cursor:
            if await cursor.fetchone():
                logger.info(f"Device {ieee} already paired, skipping")
                return

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, ?)",
            (ieee, ieee, now),
        )
        await self._db.commit()
        logger.info(f"New device paired: {ieee}")

        # Get the inserted button for broadcast
        async with self._db.execute(
            "SELECT id, ieee_addr, name, paired_at FROM buttons WHERE ieee_addr = ?",
            (ieee,),
        ) as cursor:
            row = await cursor.fetchone()

        await self._ws.broadcast("device_paired", {
            "id": row[0],
            "ieee_addr": row[1],
            "name": row[2],
            "paired_at": row[3],
        })

    async def _on_device_announce(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE buttons SET last_seen = ? WHERE ieee_addr = ?", (now, ieee)
        )
        await self._db.commit()

    async def _on_button_action(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        trigger = msg["action"]

        # Update battery + last_seen if present
        if msg.get("battery") is not None:
            await self._db.execute(
                "UPDATE buttons SET battery = ?, last_seen = ? WHERE ieee_addr = ?",
                (msg["battery"], datetime.now(timezone.utc).isoformat(), ieee),
            )
            await self._db.commit()

        # Look up button
        async with self._db.execute(
            "SELECT id FROM buttons WHERE ieee_addr = ?", (ieee,)
        ) as cursor:
            button_row = await cursor.fetchone()
        if not button_row:
            logger.warning(f"Unknown button: {ieee}")
            return

        button_id = button_row[0]

        # Look up binding
        async with self._db.execute(
            "SELECT robot_id, action, params FROM bindings "
            "WHERE button_id = ? AND trigger = ? AND enabled = 1",
            (button_id, trigger),
        ) as cursor:
            binding = await cursor.fetchone()

        if not binding:
            logger.info(f"No binding for button {ieee} trigger={trigger}")
            return

        robot_id, action, params_json = binding
        params = json.loads(params_json) if params_json else {}

        logger.info(f"Button {ieee} trigger={trigger} → {action} on {robot_id}")
        result = self._executor.execute(robot_id, action, params)

        # Log the execution
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO action_logs (button_id, trigger, robot_id, action, params, result_ok, result_detail, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                button_id,
                trigger,
                robot_id,
                action,
                params_json,
                1 if result.get("ok") else 0,
                json.dumps(result),
                now,
            ),
        )
        await self._db.commit()

        await self._ws.broadcast("action_executed", {
            "button_id": button_id,
            "trigger": trigger,
            "robot_id": robot_id,
            "action": action,
            "result": result,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_button_manager.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/services/button_manager.py tests/test_button_manager.py
git commit -m "feat: add ButtonManager for pairing and action dispatch"
```

---

## Task 7: FastAPI App + Routers

**Files:**
- Create: `src/backend/main.py`
- Create: `src/backend/routers/__init__.py`
- Create: `src/backend/routers/robots.py`
- Create: `src/backend/routers/buttons.py`
- Create: `src/backend/routers/bindings.py`
- Create: `src/backend/routers/logs.py`
- Create: `src/backend/routers/ws.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_api.py`:

```python
import pytest
import pytest_asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from httpx import AsyncClient, ASGITransport
from main import app, _state


@pytest_asyncio.fixture
async def client(tmp_path):
    os.environ["DB_PATH"] = str(tmp_path / "test.db")
    os.environ["MQTT_HOST"] = ""  # Disable MQTT in tests
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    os.environ.pop("DB_PATH", None)
    os.environ.pop("MQTT_HOST", None)


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_robots_crud(client):
    # Create
    resp = await client.post("/api/robots", json={
        "id": "r1", "name": "Test Robot", "ip": "1.2.3.4"
    })
    assert resp.status_code == 201
    # List
    resp = await client.get("/api/robots")
    assert resp.status_code == 200
    robots = resp.json()
    assert len(robots) == 1
    assert robots[0]["id"] == "r1"
    # Update
    resp = await client.put("/api/robots/r1", json={
        "name": "Updated", "ip": "5.6.7.8"
    })
    assert resp.status_code == 200
    # Delete
    resp = await client.delete("/api/robots/r1")
    assert resp.status_code == 200
    resp = await client.get("/api/robots")
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_buttons_list_empty(client):
    resp = await client.get("/api/buttons")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_bindings_get_empty(client):
    # Insert a button first
    db = _state["db"]
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00aaaaaa", "Test"),
    )
    await db.commit()
    resp = await client.get("/api/bindings/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["button_id"] == 1
    assert data["bindings"]["single"] is None
    assert data["bindings"]["double"] is None
    assert data["bindings"]["long"] is None


@pytest.mark.asyncio
async def test_bindings_put(client):
    db = _state["db"]
    await db.execute(
        "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, datetime('now'))",
        ("r1", "Robot", "1.2.3.4"),
    )
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, datetime('now'))",
        ("0x00124b00bbbbbb", "Btn"),
    )
    await db.commit()

    resp = await client.put("/api/bindings/1", json={
        "single": {"robot_id": "r1", "action": "return_home", "params": {}},
        "double": {"robot_id": "r1", "action": "speak", "params": {"text": "hi"}},
        "long": None,
    })
    assert resp.status_code == 200

    resp = await client.get("/api/bindings/1")
    data = resp.json()
    assert data["bindings"]["single"]["action"] == "return_home"
    assert data["bindings"]["double"]["action"] == "speak"
    assert data["bindings"]["long"] is None


@pytest.mark.asyncio
async def test_logs_empty(client):
    resp = await client.get("/api/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["logs"] == []
    assert data["total"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pip install httpx && .venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement main.py**

Create `src/backend/main.py`:

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.ws_manager import WSManager
from services.robot_manager import RobotManager
from services.action_executor import ActionExecutor
from services.button_manager import ButtonManager
from services.mqtt_service import MQTTService
from utils.logger import get_logger

logger = get_logger("main")

# Shared state accessible by routers
_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    db_path = os.environ.get("DB_PATH", "data/app.db")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    logger.info("Database connected and migrated")

    ws_manager = WSManager()
    robot_manager = RobotManager()
    action_executor = ActionExecutor(robot_manager)
    button_manager = ButtonManager(db, action_executor, ws_manager)

    mqtt_host = os.environ.get("MQTT_HOST", "")
    mqtt_service = None
    if mqtt_host:
        mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
        mqtt_service = MQTTService(host=mqtt_host, port=mqtt_port)
        mqtt_service.set_handler(button_manager.handle_message)
        await mqtt_service.start()

    # Load robots from DB
    async with db.execute("SELECT id, ip FROM robots WHERE enabled = 1") as cursor:
        async for row in cursor:
            try:
                robot_manager.add(row[0], row[1])
            except Exception as e:
                logger.warning(f"Failed to connect robot {row[0]} at {row[1]}: {e}")

    _state.update({
        "db": db,
        "ws_manager": ws_manager,
        "robot_manager": robot_manager,
        "action_executor": action_executor,
        "button_manager": button_manager,
        "mqtt_service": mqtt_service,
    })

    yield

    # Shutdown
    if mqtt_service:
        await mqtt_service.stop()
    robot_manager.stop_all()
    await disconnect()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
from routers import robots, buttons, bindings, logs, ws

app.include_router(robots.router, prefix="/api")
app.include_router(buttons.router, prefix="/api")
app.include_router(bindings.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


# Mount frontend static files last (catch-all)
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
```

- [ ] **Step 4: Implement robots router**

Create `src/backend/routers/__init__.py` (empty) and `src/backend/routers/robots.py`:

```python
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.robots")
router = APIRouter()


class RobotCreate(BaseModel):
    id: str
    name: str
    ip: str


class RobotUpdate(BaseModel):
    name: str
    ip: str


@router.get("/robots")
async def list_robots():
    db = _state["db"]
    async with db.execute("SELECT id, name, ip, enabled, created_at FROM robots") as cursor:
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        robot_id, name, ip, enabled, created_at = row
        online = False
        battery = None
        rm = _state.get("robot_manager")
        if rm:
            svc = rm.get(robot_id)
            if svc and svc.queries:
                try:
                    bat = svc.queries.get_battery()
                    if bat.get("ok"):
                        online = True
                        battery = bat.get("percentage")
                except Exception:
                    pass
        result.append({
            "id": robot_id, "name": name, "ip": ip,
            "enabled": bool(enabled), "created_at": created_at,
            "online": online, "battery": battery,
        })
    return result


@router.post("/robots", status_code=201)
async def create_robot(body: RobotCreate):
    db = _state["db"]
    now = datetime.now(timezone.utc).isoformat()
    try:
        await db.execute(
            "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (body.id, body.name, body.ip, now),
        )
        await db.commit()
    except Exception as e:
        raise HTTPException(400, f"Failed to create robot: {e}")
    return {"ok": True, "id": body.id}


@router.put("/robots/{robot_id}")
async def update_robot(robot_id: str, body: RobotUpdate):
    db = _state["db"]
    await db.execute(
        "UPDATE robots SET name = ?, ip = ? WHERE id = ?",
        (body.name, body.ip, robot_id),
    )
    await db.commit()
    return {"ok": True}


@router.delete("/robots/{robot_id}")
async def delete_robot(robot_id: str):
    db = _state["db"]
    rm = _state.get("robot_manager")
    if rm:
        rm.remove(robot_id)
    await db.execute("DELETE FROM robots WHERE id = ?", (robot_id,))
    await db.commit()
    return {"ok": True}


@router.get("/robots/{robot_id}/locations")
async def get_locations(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        result = svc.queries.list_locations()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/robots/{robot_id}/shortcuts")
async def get_shortcuts(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        result = svc.queries.list_shortcuts()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))
```

- [ ] **Step 5: Implement buttons router**

Create `src/backend/routers/buttons.py`:

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.buttons")
router = APIRouter()


class ButtonUpdate(BaseModel):
    name: str


@router.get("/buttons")
async def list_buttons():
    db = _state["db"]
    async with db.execute(
        "SELECT id, ieee_addr, name, paired_at, battery, last_seen FROM buttons ORDER BY id"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0], "ieee_addr": r[1], "name": r[2],
            "paired_at": r[3], "battery": r[4], "last_seen": r[5],
        }
        for r in rows
    ]


@router.put("/buttons/{button_id}")
async def update_button(button_id: int, body: ButtonUpdate):
    db = _state["db"]
    await db.execute("UPDATE buttons SET name = ? WHERE id = ?", (body.name, button_id))
    await db.commit()
    return {"ok": True}


@router.delete("/buttons/{button_id}")
async def delete_button(button_id: int):
    db = _state["db"]
    await db.execute("DELETE FROM buttons WHERE id = ?", (button_id,))
    await db.commit()
    return {"ok": True}


@router.post("/buttons/pair")
async def start_pairing():
    mqtt = _state.get("mqtt_service")
    if not mqtt:
        raise HTTPException(503, "MQTT service not available")
    await mqtt.permit_join(True, time=120)
    ws = _state.get("ws_manager")
    if ws:
        await ws.broadcast("pair_started", {"timeout": 120})
    return {"ok": True, "timeout": 120}


@router.post("/buttons/pair/stop")
async def stop_pairing():
    mqtt = _state.get("mqtt_service")
    if not mqtt:
        raise HTTPException(503, "MQTT service not available")
    await mqtt.permit_join(False)
    ws = _state.get("ws_manager")
    if ws:
        await ws.broadcast("pair_stopped", {})
    return {"ok": True}
```

- [ ] **Step 6: Implement bindings router**

Create `src/backend/routers/bindings.py`:

```python
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.bindings")
router = APIRouter()

TRIGGERS = ["single", "double", "long"]


class BindingAction(BaseModel):
    robot_id: str
    action: str
    params: dict = {}


class BindingsUpdate(BaseModel):
    single: BindingAction | None = None
    double: BindingAction | None = None
    long: BindingAction | None = None


@router.get("/bindings/{button_id}")
async def get_bindings(button_id: int):
    db = _state["db"]
    result = {"button_id": button_id, "bindings": {t: None for t in TRIGGERS}}
    async with db.execute(
        "SELECT trigger, robot_id, action, params, enabled FROM bindings WHERE button_id = ?",
        (button_id,),
    ) as cursor:
        async for row in cursor:
            trigger, robot_id, action, params, enabled = row
            result["bindings"][trigger] = {
                "robot_id": robot_id,
                "action": action,
                "params": json.loads(params) if params else {},
                "enabled": bool(enabled),
            }
    return result


@router.put("/bindings/{button_id}")
async def update_bindings(button_id: int, body: BindingsUpdate):
    db = _state["db"]
    now = datetime.now(timezone.utc).isoformat()

    # Delete all existing bindings for this button
    await db.execute("DELETE FROM bindings WHERE button_id = ?", (button_id,))

    # Insert new bindings
    for trigger in TRIGGERS:
        binding = getattr(body, trigger)
        if binding:
            await db.execute(
                "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (button_id, trigger, binding.robot_id, binding.action, json.dumps(binding.params), now),
            )
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 7: Implement logs router**

Create `src/backend/routers/logs.py`:

```python
import json
from fastapi import APIRouter, Query

from main import _state

router = APIRouter()


@router.get("/logs")
async def get_logs(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200)):
    db = _state["db"]
    offset = (page - 1) * per_page

    async with db.execute("SELECT COUNT(*) FROM action_logs") as cursor:
        total = (await cursor.fetchone())[0]

    async with db.execute(
        "SELECT al.id, al.button_id, b.name as button_name, al.trigger, al.robot_id, "
        "al.action, al.params, al.result_ok, al.result_detail, al.executed_at "
        "FROM action_logs al LEFT JOIN buttons b ON al.button_id = b.id "
        "ORDER BY al.id DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    ) as cursor:
        rows = await cursor.fetchall()

    logs = [
        {
            "id": r[0], "button_id": r[1], "button_name": r[2], "trigger": r[3],
            "robot_id": r[4], "action": r[5],
            "params": json.loads(r[6]) if r[6] else {},
            "result_ok": bool(r[7]), "result_detail": r[8], "executed_at": r[9],
        }
        for r in rows
    ]
    return {"logs": logs, "total": total, "page": page, "per_page": per_page}
```

- [ ] **Step 8: Implement WebSocket router**

Create `src/backend/routers/ws.py`:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from main import _state

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ws_manager = _state.get("ws_manager")
    if not ws_manager:
        await websocket.close()
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
```

- [ ] **Step 9: Run API tests to verify they pass**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_api.py -v`
Expected: All 7 tests PASS

- [ ] **Step 10: Commit**

```bash
git add src/backend/main.py src/backend/routers/ tests/test_api.py
git commit -m "feat: add FastAPI app with robots, buttons, bindings, logs, and WebSocket routers"
```

---

## Task 8: Frontend SPA

**Files:**
- Create: `src/frontend/index.html`
- Create: `src/frontend/css/style.css`
- Create: `src/frontend/js/api.js`
- Create: `src/frontend/js/websocket.js`
- Create: `src/frontend/js/app.js`
- Create: `src/frontend/js/robots.js`
- Create: `src/frontend/js/buttons.js`
- Create: `src/frontend/js/bindings.js`
- Create: `src/frontend/js/logs.js`

- [ ] **Step 1: Create index.html**

Create `src/frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zigbee → Kachaka Controller</title>
    <link rel="stylesheet" href="css/style.css">
</head>
<body>
    <header>
        <h1>Zigbee → Kachaka</h1>
        <nav id="tabs">
            <button class="tab active" data-tab="robots">機器人</button>
            <button class="tab" data-tab="buttons">按鈕</button>
            <button class="tab" data-tab="bindings">綁定設定</button>
            <button class="tab" data-tab="logs">執行記錄</button>
        </nav>
    </header>
    <main>
        <section id="robots" class="tab-content active"></section>
        <section id="buttons" class="tab-content"></section>
        <section id="bindings" class="tab-content"></section>
        <section id="logs" class="tab-content"></section>
    </main>
    <div id="toast" class="toast hidden"></div>
    <script type="module" src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create style.css**

Create `src/frontend/css/style.css` — a clean dark theme with responsive layout. Key selectors:

```css
:root {
    --bg: #0f0f17;
    --surface: #1a1a2e;
    --border: rgba(255,255,255,0.08);
    --text: #e0e0e0;
    --text-muted: #888;
    --primary: #818cf8;
    --success: #4ade80;
    --danger: #f87171;
    --warning: #fbbf24;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); }
header { padding: 1rem 1.5rem; border-bottom: 1px solid var(--border); }
header h1 { font-size: 1.2rem; margin-bottom: 0.75rem; }
nav#tabs { display: flex; gap: 0; }
.tab { background: none; border: none; color: var(--text-muted); padding: 0.6rem 1.2rem; cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent; }
.tab.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
main { padding: 1.5rem; max-width: 960px; margin: 0 auto; }
.tab-content { display: none; }
.tab-content.active { display: block; }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.card-header h2 { font-size: 1rem; }

table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: left; padding: 0.5rem; color: var(--text-muted); border-bottom: 1px solid var(--border); }
td { padding: 0.5rem; border-bottom: 1px solid var(--border); }

.btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
.btn-primary { background: var(--primary); color: white; }
.btn-success { background: var(--success); color: #000; }
.btn-danger { background: rgba(248,113,113,0.2); color: var(--danger); border: 1px solid var(--danger); }
.btn-sm { padding: 0.3rem 0.6rem; font-size: 0.78rem; }

.form-group { margin-bottom: 0.75rem; }
.form-group label { display: block; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.25rem; }
.form-group input, .form-group select { width: 100%; padding: 0.5rem; background: rgba(255,255,255,0.05); border: 1px solid var(--border); border-radius: 4px; color: var(--text); font-size: 0.85rem; }

.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.3rem; }
.status-online { background: var(--success); }
.status-offline { background: var(--danger); }

.pair-zone { margin-top: 1rem; padding: 1rem; border: 2px dashed var(--success); border-radius: 8px; background: rgba(74,222,128,0.05); }
.pair-zone.hidden { display: none; }

.trigger-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
.trigger-slot { border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
.trigger-slot h4 { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 0.75rem; }

.toast { position: fixed; bottom: 1.5rem; right: 1.5rem; padding: 0.75rem 1.2rem; border-radius: 8px; font-size: 0.85rem; z-index: 1000; transition: opacity 0.3s; }
.toast.hidden { opacity: 0; pointer-events: none; }
.toast.success { background: var(--success); color: #000; }
.toast.error { background: var(--danger); color: white; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; width: 90%; max-width: 420px; }
.modal h3 { margin-bottom: 1rem; }
.modal-actions { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
```

- [ ] **Step 3: Create api.js**

Create `src/frontend/js/api.js`:

```javascript
const BASE = '/api';

async function request(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const resp = await fetch(BASE + path, opts);
    if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err);
    }
    return resp.json();
}

export const api = {
    // Robots
    listRobots: () => request('GET', '/robots'),
    createRobot: (data) => request('POST', '/robots', data),
    updateRobot: (id, data) => request('PUT', `/robots/${id}`, data),
    deleteRobot: (id) => request('DELETE', `/robots/${id}`),
    getLocations: (id) => request('GET', `/robots/${id}/locations`),
    getShortcuts: (id) => request('GET', `/robots/${id}/shortcuts`),

    // Buttons
    listButtons: () => request('GET', '/buttons'),
    updateButton: (id, data) => request('PUT', `/buttons/${id}`, data),
    deleteButton: (id) => request('DELETE', `/buttons/${id}`),
    startPairing: () => request('POST', '/buttons/pair'),
    stopPairing: () => request('POST', '/buttons/pair/stop'),

    // Bindings
    getBindings: (buttonId) => request('GET', `/bindings/${buttonId}`),
    updateBindings: (buttonId, data) => request('PUT', `/bindings/${buttonId}`, data),

    // Logs
    getLogs: (page = 1) => request('GET', `/logs?page=${page}`),
};
```

- [ ] **Step 4: Create websocket.js**

Create `src/frontend/js/websocket.js`:

```javascript
class WS {
    constructor() {
        this._handlers = {};
        this._ws = null;
        this._reconnectDelay = 1000;
    }

    connect() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this._ws = new WebSocket(`${proto}//${location.host}/ws`);
        this._ws.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                const handlers = this._handlers[msg.event] || [];
                handlers.forEach(h => h(msg.data));
            } catch {}
        };
        this._ws.onclose = () => {
            setTimeout(() => this.connect(), this._reconnectDelay);
        };
    }

    on(event, handler) {
        if (!this._handlers[event]) this._handlers[event] = [];
        this._handlers[event].push(handler);
    }
}

export const ws = new WS();
```

- [ ] **Step 5: Create app.js**

Create `src/frontend/js/app.js`:

```javascript
import { ws } from './websocket.js';
import { initRobots } from './robots.js';
import { initButtons } from './buttons.js';
import { initBindings } from './bindings.js';
import { initLogs } from './logs.js';

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(tab.dataset.tab).classList.add('active');
    });
});

// Toast notification
export function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

// Modal helper
export function showModal(title, bodyHtml, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal">
            <h3>${title}</h3>
            <div>${bodyHtml}</div>
            <div class="modal-actions">
                <button class="btn btn-danger" id="modal-cancel">取消</button>
                <button class="btn btn-primary" id="modal-confirm">確認</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('#modal-cancel').onclick = () => overlay.remove();
    overlay.querySelector('#modal-confirm').onclick = () => {
        onConfirm(overlay);
        overlay.remove();
    };
    return overlay;
}

// Init
ws.connect();
initRobots();
initButtons(ws);
initBindings();
initLogs(ws);
```

- [ ] **Step 6: Create robots.js**

Create `src/frontend/js/robots.js`:

```javascript
import { api } from './api.js';
import { showToast, showModal } from './app.js';

const container = document.getElementById('robots');

export async function initRobots() {
    await renderRobots();
}

async function renderRobots() {
    const robots = await api.listRobots();
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h2>已註冊機器人</h2>
                <button class="btn btn-primary" id="add-robot">+ 新增機器人</button>
            </div>
            <table>
                <thead><tr><th>名稱</th><th>IP</th><th>狀態</th><th>電量</th><th>操作</th></tr></thead>
                <tbody>
                    ${robots.map(r => `
                        <tr>
                            <td>${r.name}</td>
                            <td style="color:var(--text-muted)">${r.ip}</td>
                            <td><span class="status-dot ${r.online ? 'status-online' : 'status-offline'}"></span>${r.online ? '在線' : '離線'}</td>
                            <td>${r.battery != null ? r.battery + '%' : '—'}</td>
                            <td>
                                <button class="btn btn-sm btn-primary edit-robot" data-id="${r.id}" data-name="${r.name}" data-ip="${r.ip}">編輯</button>
                                <button class="btn btn-sm btn-danger del-robot" data-id="${r.id}">刪除</button>
                            </td>
                        </tr>
                    `).join('')}
                    ${robots.length === 0 ? '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無機器人，點擊「新增」添加</td></tr>' : ''}
                </tbody>
            </table>
        </div>
    `;

    container.querySelector('#add-robot').onclick = () => {
        showModal('新增機器人', `
            <div class="form-group"><label>ID</label><input id="r-id" placeholder="kachaka-1"></div>
            <div class="form-group"><label>名稱</label><input id="r-name" placeholder="大廳機器人"></div>
            <div class="form-group"><label>IP</label><input id="r-ip" placeholder="192.168.50.101"></div>
        `, async () => {
            try {
                await api.createRobot({
                    id: document.getElementById('r-id').value,
                    name: document.getElementById('r-name').value,
                    ip: document.getElementById('r-ip').value,
                });
                showToast('機器人已新增');
                await renderRobots();
            } catch (e) { showToast(e.message, 'error'); }
        });
    };

    container.querySelectorAll('.edit-robot').forEach(btn => {
        btn.onclick = () => {
            const { id, name, ip } = btn.dataset;
            showModal('編輯機器人', `
                <div class="form-group"><label>名稱</label><input id="r-name" value="${name}"></div>
                <div class="form-group"><label>IP</label><input id="r-ip" value="${ip}"></div>
            `, async () => {
                try {
                    await api.updateRobot(id, {
                        name: document.getElementById('r-name').value,
                        ip: document.getElementById('r-ip').value,
                    });
                    showToast('已更新');
                    await renderRobots();
                } catch (e) { showToast(e.message, 'error'); }
            });
        };
    });

    container.querySelectorAll('.del-robot').forEach(btn => {
        btn.onclick = async () => {
            if (confirm('確定刪除此機器人？')) {
                await api.deleteRobot(btn.dataset.id);
                showToast('已刪除');
                await renderRobots();
            }
        };
    });
}
```

- [ ] **Step 7: Create buttons.js**

Create `src/frontend/js/buttons.js`:

```javascript
import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('buttons');
let pairTimer = null;

export async function initButtons(ws) {
    ws.on('device_paired', async () => {
        showToast('新設備已配對!');
        await renderButtons();
    });
    await renderButtons();
}

async function renderButtons() {
    const buttons = await api.listButtons();
    container.innerHTML = `
        <div class="card">
            <div class="card-header">
                <h2>已配對按鈕</h2>
                <button class="btn btn-success" id="start-pair">開始配對</button>
            </div>
            <table>
                <thead><tr><th>名稱</th><th>IEEE 位址</th><th>電量</th><th>最後回報</th><th>操作</th></tr></thead>
                <tbody>
                    ${buttons.map(b => `
                        <tr>
                            <td>${b.name || b.ieee_addr}</td>
                            <td style="color:var(--text-muted);font-size:0.78rem">${b.ieee_addr}</td>
                            <td>${b.battery != null ? '🔋 ' + b.battery + '%' : '—'}</td>
                            <td style="color:var(--text-muted);font-size:0.78rem">${b.last_seen || '—'}</td>
                            <td>
                                <button class="btn btn-sm btn-primary rename-btn" data-id="${b.id}" data-name="${b.name || ''}">重命名</button>
                                <button class="btn btn-sm btn-danger del-btn" data-id="${b.id}">移除</button>
                            </td>
                        </tr>
                    `).join('')}
                    ${buttons.length === 0 ? '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無配對按鈕</td></tr>' : ''}
                </tbody>
            </table>
        </div>
        <div class="pair-zone hidden" id="pair-zone">
            <h4 style="color:var(--success)">配對模式啟動中...</h4>
            <p style="font-size:0.82rem;color:var(--text-muted);margin-top:0.5rem">請長按 SNZB-01 按鈕 5 秒直到 LED 閃爍</p>
            <p style="margin-top:0.5rem;font-size:0.82rem;color:var(--success)" id="pair-countdown"></p>
            <button class="btn btn-danger" style="margin-top:0.75rem" id="stop-pair">停止配對</button>
        </div>
    `;

    container.querySelector('#start-pair').onclick = async () => {
        try {
            await api.startPairing();
            const zone = document.getElementById('pair-zone');
            zone.classList.remove('hidden');
            let remaining = 120;
            document.getElementById('pair-countdown').textContent = `等待設備加入... (${remaining}s)`;
            pairTimer = setInterval(() => {
                remaining--;
                const el = document.getElementById('pair-countdown');
                if (el) el.textContent = `等待設備加入... (${remaining}s)`;
                if (remaining <= 0) { clearInterval(pairTimer); zone.classList.add('hidden'); }
            }, 1000);
        } catch (e) { showToast(e.message, 'error'); }
    };

    const stopBtn = container.querySelector('#stop-pair');
    if (stopBtn) {
        stopBtn.onclick = async () => {
            clearInterval(pairTimer);
            await api.stopPairing();
            document.getElementById('pair-zone').classList.add('hidden');
        };
    }

    container.querySelectorAll('.rename-btn').forEach(btn => {
        btn.onclick = async () => {
            const name = prompt('新名稱:', btn.dataset.name);
            if (name) {
                await api.updateButton(btn.dataset.id, { name });
                showToast('已重命名');
                await renderButtons();
            }
        };
    });

    container.querySelectorAll('.del-btn').forEach(btn => {
        btn.onclick = async () => {
            if (confirm('確定移除此按鈕？')) {
                await api.deleteButton(btn.dataset.id);
                showToast('已移除');
                await renderButtons();
            }
        };
    });
}
```

- [ ] **Step 8: Create bindings.js**

Create `src/frontend/js/bindings.js`:

```javascript
import { api } from './api.js';
import { showToast } from './app.js';

const container = document.getElementById('bindings');
const TRIGGERS = ['single', 'double', 'long'];
const TRIGGER_LABELS = { single: '單擊', double: '雙擊', long: '長按' };
const ACTIONS = [
    { value: 'move_to_location', label: '移動到位置' },
    { value: 'return_home', label: '回充電座' },
    { value: 'speak', label: '語音播報' },
    { value: 'move_shelf', label: '搬運貨架' },
    { value: 'return_shelf', label: '歸還貨架' },
    { value: 'dock_shelf', label: '對接貨架' },
    { value: 'undock_shelf', label: '放下貨架' },
    { value: 'start_shortcut', label: '執行捷徑' },
];

export async function initBindings() {
    await renderBindings();
}

async function renderBindings() {
    const buttons = await api.listButtons();
    const robots = await api.listRobots();

    container.innerHTML = `
        <div class="card">
            <div class="card-header"><h2>按鈕動作綁定</h2></div>
            ${buttons.length === 0 ? '<p style="color:var(--text-muted)">請先配對按鈕</p>' : `
            <div class="form-group">
                <label>選擇按鈕</label>
                <select id="bind-button-select">
                    ${buttons.map(b => `<option value="${b.id}">${b.name || b.ieee_addr}</option>`).join('')}
                </select>
            </div>
            <div id="trigger-slots"></div>
            <div style="margin-top:1rem;text-align:right">
                <button class="btn btn-primary" id="save-bindings">儲存設定</button>
            </div>
            `}
        </div>
    `;

    if (buttons.length === 0) return;

    const selectEl = container.querySelector('#bind-button-select');
    selectEl.onchange = () => loadBindings(selectEl.value, robots);
    await loadBindings(selectEl.value, robots);

    container.querySelector('#save-bindings').onclick = () => saveBindings(selectEl.value);
}

async function loadBindings(buttonId, robots) {
    const data = await api.getBindings(buttonId);
    const slotsDiv = container.querySelector('#trigger-slots');

    slotsDiv.innerHTML = `<div class="trigger-grid">${TRIGGERS.map(t => {
        const b = data.bindings[t];
        return `
        <div class="trigger-slot" data-trigger="${t}">
            <h4>${TRIGGER_LABELS[t]}</h4>
            <div class="form-group">
                <label>機器人</label>
                <select class="bind-robot">
                    <option value="">-- 不設定 --</option>
                    ${robots.map(r => `<option value="${r.id}" ${b && b.robot_id === r.id ? 'selected' : ''}>${r.name}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label>動作</label>
                <select class="bind-action">
                    <option value="">-- 選擇動作 --</option>
                    ${ACTIONS.map(a => `<option value="${a.value}" ${b && b.action === a.value ? 'selected' : ''}>${a.label}</option>`).join('')}
                </select>
            </div>
            <div class="bind-params"></div>
        </div>`;
    }).join('')}</div>`;

    // Setup dynamic param fields
    slotsDiv.querySelectorAll('.trigger-slot').forEach(slot => {
        const trigger = slot.dataset.trigger;
        const b = data.bindings[trigger];
        const actionSelect = slot.querySelector('.bind-action');
        const robotSelect = slot.querySelector('.bind-robot');
        const paramsDiv = slot.querySelector('.bind-params');

        const renderParams = async () => {
            const action = actionSelect.value;
            const robotId = robotSelect.value;
            paramsDiv.innerHTML = '';
            if (!action) return;

            if (action === 'move_to_location' && robotId) {
                try {
                    const locData = await api.getLocations(robotId);
                    const locations = locData.locations || [];
                    const current = b && b.action === action ? b.params.name : '';
                    paramsDiv.innerHTML = `<div class="form-group"><label>位置</label>
                        <select class="param-name">
                            ${locations.map(l => `<option value="${l.name}" ${l.name === current ? 'selected' : ''}>${l.name}</option>`).join('')}
                        </select></div>`;
                } catch { paramsDiv.innerHTML = '<p style="color:var(--danger);font-size:0.8rem">無法取得位置清單</p>'; }
            } else if (action === 'speak') {
                const current = b && b.action === action ? b.params.text : '';
                paramsDiv.innerHTML = `<div class="form-group"><label>內容</label><input class="param-text" value="${current}"></div>`;
            } else if (action === 'move_shelf') {
                const cs = b && b.action === action ? b.params.shelf : '';
                const cl = b && b.action === action ? b.params.location : '';
                paramsDiv.innerHTML = `
                    <div class="form-group"><label>貨架名稱</label><input class="param-shelf" value="${cs}"></div>
                    <div class="form-group"><label>目標位置</label><input class="param-location" value="${cl}"></div>`;
            } else if (action === 'return_shelf') {
                const cs = b && b.action === action ? b.params.shelf : '';
                paramsDiv.innerHTML = `<div class="form-group"><label>貨架名稱</label><input class="param-shelf" value="${cs}"></div>`;
            } else if (action === 'start_shortcut' && robotId) {
                try {
                    const scData = await api.getShortcuts(robotId);
                    const shortcuts = scData.shortcuts || [];
                    const current = b && b.action === action ? b.params.shortcut_id : '';
                    paramsDiv.innerHTML = `<div class="form-group"><label>捷徑</label>
                        <select class="param-shortcut_id">
                            ${shortcuts.map(s => `<option value="${s.id}" ${s.id === current ? 'selected' : ''}>${s.name || s.id}</option>`).join('')}
                        </select></div>`;
                } catch { paramsDiv.innerHTML = '<p style="color:var(--danger);font-size:0.8rem">無法取得捷徑清單</p>'; }
            }
        };

        actionSelect.onchange = renderParams;
        robotSelect.onchange = renderParams;
        renderParams();
    });
}

async function saveBindings(buttonId) {
    const payload = {};
    container.querySelectorAll('.trigger-slot').forEach(slot => {
        const trigger = slot.dataset.trigger;
        const robotId = slot.querySelector('.bind-robot').value;
        const action = slot.querySelector('.bind-action').value;
        if (!robotId || !action) { payload[trigger] = null; return; }

        let params = {};
        const paramsDiv = slot.querySelector('.bind-params');
        if (action === 'move_to_location') params = { name: paramsDiv.querySelector('.param-name')?.value || '' };
        else if (action === 'speak') params = { text: paramsDiv.querySelector('.param-text')?.value || '' };
        else if (action === 'move_shelf') params = { shelf: paramsDiv.querySelector('.param-shelf')?.value || '', location: paramsDiv.querySelector('.param-location')?.value || '' };
        else if (action === 'return_shelf') params = { shelf: paramsDiv.querySelector('.param-shelf')?.value || '' };
        else if (action === 'start_shortcut') params = { shortcut_id: paramsDiv.querySelector('.param-shortcut_id')?.value || '' };

        payload[trigger] = { robot_id: robotId, action, params };
    });

    try {
        await api.updateBindings(buttonId, payload);
        showToast('設定已儲存');
    } catch (e) { showToast(e.message, 'error'); }
}
```

- [ ] **Step 9: Create logs.js**

Create `src/frontend/js/logs.js`:

```javascript
import { api } from './api.js';

const container = document.getElementById('logs');
const ACTION_LABELS = {
    move_to_location: '移動', return_home: '回家', speak: '語音',
    move_shelf: '搬貨架', return_shelf: '還貨架', dock_shelf: '對接',
    undock_shelf: '放下', start_shortcut: '捷徑',
};

export async function initLogs(ws) {
    ws.on('action_executed', () => renderLogs());
    await renderLogs();
}

async function renderLogs(page = 1) {
    const data = await api.getLogs(page);
    container.innerHTML = `
        <div class="card">
            <div class="card-header"><h2>執行記錄</h2></div>
            <table>
                <thead><tr><th>時間</th><th>按鈕</th><th>動作</th><th>機器人</th><th>結果</th></tr></thead>
                <tbody>
                    ${data.logs.map(l => `
                        <tr>
                            <td style="color:var(--text-muted);font-size:0.82rem">${l.executed_at ? new Date(l.executed_at).toLocaleString('zh-TW') : '—'}</td>
                            <td>${l.button_name || l.button_id}</td>
                            <td>${ACTION_LABELS[l.action] || l.action}${l.action === 'move_to_location' ? ' → ' + (l.params.name || '') : l.action === 'speak' ? ' → "' + (l.params.text || '') + '"' : ''}</td>
                            <td style="color:var(--text-muted)">${l.robot_id}</td>
                            <td style="color:${l.result_ok ? 'var(--success)' : 'var(--danger)'}">${l.result_ok ? '✓' : '✗'}</td>
                        </tr>
                    `).join('')}
                    ${data.logs.length === 0 ? '<tr><td colspan="5" style="text-align:center;color:var(--text-muted)">尚無執行記錄</td></tr>' : ''}
                </tbody>
            </table>
            ${data.total > data.per_page ? `
            <div style="margin-top:1rem;display:flex;gap:0.5rem;justify-content:center">
                ${page > 1 ? `<button class="btn btn-sm btn-primary" id="prev-page">上一頁</button>` : ''}
                <span style="padding:0.3rem 0.6rem;color:var(--text-muted);font-size:0.82rem">${page} / ${Math.ceil(data.total / data.per_page)}</span>
                ${page * data.per_page < data.total ? `<button class="btn btn-sm btn-primary" id="next-page">下一頁</button>` : ''}
            </div>` : ''}
        </div>
    `;

    container.querySelector('#prev-page')?.addEventListener('click', () => renderLogs(page - 1));
    container.querySelector('#next-page')?.addEventListener('click', () => renderLogs(page + 1));
}
```

- [ ] **Step 10: Verify frontend loads**

Run: `cd /home/snaken/CodeBase/pi-zigbee && ls src/frontend/js/*.js src/frontend/css/*.css src/frontend/index.html`
Expected: All 7 JS files, 1 CSS file, 1 HTML file listed

- [ ] **Step 11: Commit**

```bash
git add src/frontend/
git commit -m "feat: add Vanilla JS SPA frontend with 4 tabs"
```

---

## Task 9: Docker & Infrastructure

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `docker-compose.override.yml`
- Create: `mosquitto/mosquitto.conf`
- Create: `zigbee2mqtt/configuration.yaml`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Create Dockerfile**

Create `Dockerfile`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
COPY src/ src/
ENV PYTHONPATH=src/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

- [ ] **Step 2: Create docker-compose.yml (dev)**

Create `docker-compose.yml`:

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf
    restart: unless-stopped

  zigbee2mqtt:
    image: koenkk/zigbee2mqtt
    ports:
      - "8080:8080"
    volumes:
      - ./zigbee2mqtt:/app/data
    devices:
      - ${ZIGBEE_DEVICE:-/dev/ttyACM0}:/dev/ttyACM0
    environment:
      - TZ=Asia/Taipei
    depends_on:
      - mosquitto
    restart: unless-stopped

  app:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    environment:
      - MQTT_HOST=mosquitto
      - MQTT_PORT=1883
      - TZ=Asia/Taipei
    depends_on:
      - mosquitto
    restart: unless-stopped
```

- [ ] **Step 3: Create docker-compose.override.yml (dev live reload)**

Create `docker-compose.override.yml`:

```yaml
services:
  app:
    volumes:
      - ./src:/app/src
      - ./data:/app/data
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 4: Create mosquitto.conf**

Create `mosquitto/mosquitto.conf`:

```
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
```

- [ ] **Step 5: Create zigbee2mqtt configuration.yaml**

Create `zigbee2mqtt/configuration.yaml`:

```yaml
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto
serial:
  port: /dev/ttyACM0
frontend:
  port: 8080
advanced:
  log_level: info
  homeassistant_legacy_entity_attributes: false
  legacy_api: false
  legacy_availability_payload: false
permit_join: false
```

- [ ] **Step 6: Create .env.example**

Create `.env.example`:

```
MQTT_HOST=mosquitto
MQTT_PORT=1883
ZIGBEE_DEVICE=/dev/ttyACM0
TZ=Asia/Taipei
```

- [ ] **Step 7: Update .gitignore**

Append to `.gitignore`:

```
.venv/
__pycache__/
*.pyc
.env
zigbee2mqtt/state.json
zigbee2mqtt/database.db
zigbee2mqtt/coordinator_backup.json
zigbee2mqtt/log/
```

- [ ] **Step 8: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.override.yml mosquitto/ zigbee2mqtt/configuration.yaml .env.example .gitignore
git commit -m "feat: add Docker infrastructure (dev compose, Mosquitto, Zigbee2MQTT)"
```

---

## Task 10: Production Deploy + GitHub CI

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`
- Create: `deploy/daemon.json`
- Create: `deploy/setup.sh`
- Create: `.github/workflows/build.yml`

- [ ] **Step 1: Create deploy/docker-compose.yml (prod)**

Create `deploy/docker-compose.yml`:

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf
    restart: unless-stopped

  zigbee2mqtt:
    image: koenkk/zigbee2mqtt
    ports:
      - "8080:8080"
    volumes:
      - ./zigbee2mqtt:/app/data
    devices:
      - ${ZIGBEE_DEVICE:-/dev/ttyACM0}:/dev/ttyACM0
    environment:
      - TZ=Asia/Taipei
    depends_on:
      - mosquitto
    restart: unless-stopped

  app:
    image: ghcr.io/sigma-snaken/pi-zigbee:latest
    ports:
      - "8000:8000"
    dns:
      - 8.8.8.8
      - 1.1.1.1
    sysctls:
      - net.ipv6.conf.all.disable_ipv6=1
    volumes:
      - ./data:/app/data
    environment:
      - MQTT_HOST=mosquitto
      - MQTT_PORT=1883
      - TZ=Asia/Taipei
    depends_on:
      - mosquitto
    restart: unless-stopped
```

- [ ] **Step 2: Create deploy/.env.example**

Create `deploy/.env.example`:

```
ZIGBEE_DEVICE=/dev/ttyACM0
TZ=Asia/Taipei
```

- [ ] **Step 3: Create deploy/daemon.json**

Create `deploy/daemon.json`:

```json
{
  "ipv6": false,
  "dns": ["8.8.8.8", "1.1.1.1"]
}
```

- [ ] **Step 4: Create deploy/setup.sh**

Create `deploy/setup.sh`:

```bash
#!/bin/bash
set -euo pipefail

echo "=== Pi Zigbee Controller — First-time Setup ==="

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and back in, then re-run this script."
    exit 0
fi

# Configure Docker daemon for IPv4
echo "Configuring Docker daemon..."
sudo cp daemon.json /etc/docker/daemon.json
sudo systemctl restart docker

# Create app directory
APP_DIR=/opt/app/pi-zigbee
sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

# Copy deploy files
cp docker-compose.yml "$APP_DIR/"
mkdir -p "$APP_DIR/data"
mkdir -p "$APP_DIR/mosquitto"
mkdir -p "$APP_DIR/zigbee2mqtt"

# Copy configs if not exist
if [ ! -f "$APP_DIR/mosquitto/mosquitto.conf" ]; then
    cat > "$APP_DIR/mosquitto/mosquitto.conf" << 'EOF'
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
EOF
fi

if [ ! -f "$APP_DIR/zigbee2mqtt/configuration.yaml" ]; then
    cat > "$APP_DIR/zigbee2mqtt/configuration.yaml" << 'EOF'
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://mosquitto
serial:
  port: /dev/ttyACM0
frontend:
  port: 8080
advanced:
  log_level: info
permit_join: false
EOF
fi

# Create .env if not exist
if [ ! -f "$APP_DIR/.env" ]; then
    cp .env.example "$APP_DIR/.env"
    echo "Created .env from template. Edit $APP_DIR/.env if needed."
fi

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Verify Zigbee dongle: ls /dev/ttyACM* /dev/ttyUSB*"
echo "  2. Edit $APP_DIR/.env if the device path differs"
echo "  3. cd $APP_DIR && docker compose pull && docker compose up -d"
```

- [ ] **Step 5: Create GitHub CI workflow**

Create `.github/workflows/build.yml`:

```yaml
name: Build & Push Docker Image

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          push: true
          platforms: linux/amd64,linux/arm64
          tags: |
            ghcr.io/${{ github.repository }}:latest
            ghcr.io/${{ github.repository }}:${{ github.sha }}
```

- [ ] **Step 6: Make setup.sh executable and commit**

```bash
chmod +x deploy/setup.sh
git add deploy/ .github/
git commit -m "feat: add production deploy config and GitHub CI workflow"
```

---

## Task 11: Integration Test — Full Stack Smoke Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration smoke test**

Create `tests/test_integration.py`:

```python
"""
Smoke test: verifies the full flow from MQTT message → DB lookup → action execution.
Does NOT require a real MQTT broker or Kachaka robot.
"""
import pytest
import pytest_asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "backend"))

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.ws_manager import WSManager
from services.robot_manager import RobotManager, RobotService
from services.action_executor import ActionExecutor
from services.button_manager import ButtonManager
from services.mqtt_service import parse_zigbee_message


class FakeConnection:
    def __init__(self, ip):
        self.ip = ip

    def ping(self):
        return {"ok": True, "serial": "KCK-TEST"}


class FakeCommands:
    def __init__(self, conn):
        self.calls = []

    def move_to_location(self, name):
        self.calls.append(("move_to_location", name))
        return {"ok": True, "action": "move_to_location", "target": name}

    def return_home(self):
        self.calls.append(("return_home",))
        return {"ok": True, "action": "return_home"}

    def speak(self, text):
        self.calls.append(("speak", text))
        return {"ok": True, "action": "speak"}

    def start_shortcut(self, shortcut_id):
        self.calls.append(("start_shortcut", shortcut_id))
        return {"ok": True, "action": "start_shortcut"}


class FakeQueries:
    def __init__(self, conn):
        pass


class FakeWSManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, event, data):
        self.events.append((event, data))


@pytest_asyncio.fixture
async def stack(tmp_path):
    db_path = str(tmp_path / "test.db")
    await connect(db_path)
    db = get_db()
    await run_migrations(db)

    robot_mgr = RobotManager()
    robot_mgr.add("r1", "1.2.3.4", connect_fn=lambda ip: FakeConnection(ip),
                   commands_cls=FakeCommands, queries_cls=FakeQueries)
    executor = ActionExecutor(robot_mgr)
    ws = FakeWSManager()
    btn_mgr = ButtonManager(db, executor, ws)

    yield db, robot_mgr, btn_mgr, ws
    await disconnect()


@pytest.mark.asyncio
async def test_full_flow_button_press_to_robot_action(stack):
    db, robot_mgr, btn_mgr, ws = stack

    # 1. Simulate device join
    join_msg = parse_zigbee_message(
        "zigbee2mqtt/bridge/event",
        json.dumps({"type": "device_joined", "data": {"ieee_address": "0x00124b00test01", "friendly_name": "0x00124b00test01"}}),
    )
    await btn_mgr.handle_message(join_msg)

    # Verify button was created
    async with db.execute("SELECT id FROM buttons WHERE ieee_addr = '0x00124b00test01'") as cursor:
        btn_row = await cursor.fetchone()
    assert btn_row is not None
    button_id = btn_row[0]

    # 2. Create binding: single click → move to Kitchen
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) "
        "VALUES (?, 'single', 'r1', 'move_to_location', ?, 1, datetime('now'))",
        (button_id, json.dumps({"name": "Kitchen"})),
    )
    await db.commit()

    # 3. Simulate button press
    action_msg = parse_zigbee_message(
        "zigbee2mqtt/0x00124b00test01",
        json.dumps({"action": "single", "battery": 90}),
    )
    await btn_mgr.handle_message(action_msg)

    # 4. Verify robot received the command
    svc = robot_mgr.get("r1")
    assert ("move_to_location", "Kitchen") in svc.commands.calls

    # 5. Verify action was logged
    async with db.execute("SELECT action, result_ok FROM action_logs") as cursor:
        log = await cursor.fetchone()
    assert log[0] == "move_to_location"
    assert log[1] == 1

    # 6. Verify WebSocket events were broadcast
    event_types = [e[0] for e in ws.events]
    assert "device_paired" in event_types
    assert "action_executed" in event_types


@pytest.mark.asyncio
async def test_full_flow_three_triggers(stack):
    db, robot_mgr, btn_mgr, ws = stack

    # Setup button + 3 bindings
    await db.execute(
        "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES ('0x00124b00test02', 'Test', datetime('now'))"
    )
    await db.execute(
        "INSERT INTO bindings (button_id, trigger, robot_id, action, params, enabled, created_at) VALUES "
        "(1, 'single', 'r1', 'move_to_location', '{\"name\":\"Kitchen\"}', 1, datetime('now')),"
        "(1, 'double', 'r1', 'speak', '{\"text\":\"hello\"}', 1, datetime('now')),"
        "(1, 'long', 'r1', 'return_home', '{}', 1, datetime('now'))"
    )
    await db.commit()

    for trigger in ["single", "double", "long"]:
        msg = parse_zigbee_message(
            "zigbee2mqtt/0x00124b00test02",
            json.dumps({"action": trigger}),
        )
        await btn_mgr.handle_message(msg)

    svc = robot_mgr.get("r1")
    assert ("move_to_location", "Kitchen") in svc.commands.calls
    assert ("speak", "hello") in svc.commands.calls
    assert ("return_home",) in svc.commands.calls

    async with db.execute("SELECT COUNT(*) FROM action_logs") as cursor:
        count = (await cursor.fetchone())[0]
    assert count == 3
```

- [ ] **Step 2: Run integration tests**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/test_integration.py -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Run all tests**

Run: `cd /home/snaken/CodeBase/pi-zigbee && .venv/bin/pytest tests/ -v`
Expected: All tests PASS (database: 4, ws_manager: 3, robot_manager: 3, action_executor: 6, mqtt_service: 8, button_manager: 5, api: 7, integration: 2 = 38 total)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration smoke test for full button→robot flow"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Goal 1 (kachaka-sdk-toolkit control) → Task 3 (RobotManager), Task 4 (ActionExecutor)
- [x] Goal 2 (Web UI pairing) → Task 8 (Frontend), Task 7 (buttons router), Task 6 (ButtonManager)
- [x] Goal 3 (button → action binding) → Task 6 (ButtonManager), Task 7 (bindings router), Task 8 (bindings.js)
- [x] Database schema (4 tables) → Task 1
- [x] All 8 supported actions → Task 4
- [x] MQTT subscription → Task 5
- [x] WebSocket real-time → Task 2, Task 7 (ws router)
- [x] Docker dev/prod split → Task 9, Task 10
- [x] GitHub CI → Task 10
- [x] Deploy scripts → Task 10

**Placeholder scan:** No TBD/TODO found.

**Type consistency:** Verified: `RobotService`, `RobotManager`, `ActionExecutor`, `ButtonManager`, `MQTTService`, `WSManager` — method names and signatures are consistent across all tasks and tests.
