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
