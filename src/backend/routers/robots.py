import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.robots")
router = APIRouter()


class RobotCreate(BaseModel):
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
    rm = _state.get("robot_manager")
    for row in rows:
        robot_id, name, ip, enabled, created_at = row
        online = False
        battery = None
        serial = None
        connection_state = "unknown"
        moving_shelf_id = None
        if rm:
            svc = rm.get(robot_id)
            if svc and svc.conn:
                from kachaka_core.connection import ConnectionState
                online = svc.conn.state == ConnectionState.CONNECTED
                serial = svc.conn.serial or None
                if svc.controller:
                    state = svc.controller.state
                    battery = getattr(state, 'battery_pct', None)
                    connection_state = getattr(state, 'connection_state', 'unknown')
                    moving_shelf_id = getattr(state, 'moving_shelf_id', None)
        result.append({
            "id": robot_id, "name": name, "ip": ip,
            "enabled": bool(enabled), "created_at": created_at,
            "online": online, "battery": battery, "serial": serial,
            "connection_state": connection_state,
            "moving_shelf_id": moving_shelf_id,
        })
    return result


@router.post("/robots", status_code=201)
async def create_robot(body: RobotCreate):
    if not body.name or not body.name.strip():
        raise HTTPException(400, "Robot name is required")
    robot_id = body.name.strip()
    db = _state["db"]
    now = datetime.now(timezone.utc).isoformat()
    try:
        await db.execute(
            "INSERT INTO robots (id, name, ip, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (robot_id, body.name.strip(), body.ip.strip(), now),
        )
        await db.commit()
    except Exception as e:
        raise HTTPException(400, f"Failed to create robot: {e}")
    # Connect in background — return immediately so the UI stays responsive.
    # Connection result is pushed via WebSocket (robot:connection event).
    rm = _state.get("robot_manager")
    if rm:
        loop = asyncio.get_event_loop()
        ip = body.ip.strip()

        def _bg_connect():
            try:
                rm.add(robot_id, ip)
            except Exception as e:
                logger.warning(f"Robot added to DB but connection failed: {e}")

        loop.run_in_executor(None, _bg_connect)
    return {"ok": True, "id": robot_id}


@router.put("/robots/{robot_id}")
async def update_robot(robot_id: str, body: RobotUpdate):
    db = _state["db"]
    # Check if IP changed — need to reconnect
    old_ip = None
    async with db.execute("SELECT ip FROM robots WHERE id = ?", (robot_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            old_ip = row[0]
    await db.execute("UPDATE robots SET name = ?, ip = ? WHERE id = ?", (body.name, body.ip, robot_id))
    await db.commit()
    # Reconnect if IP changed
    rm = _state.get("robot_manager")
    new_ip = body.ip.strip()
    if rm and old_ip and old_ip != new_ip:
        loop = asyncio.get_event_loop()

        def _bg_reconnect():
            try:
                rm.remove(robot_id)
                rm.add(robot_id, new_ip)
            except Exception as e:
                logger.warning(f"Reconnect failed for {robot_id}: {e}")

        loop.run_in_executor(None, _bg_reconnect)
    return {"ok": True}


@router.delete("/robots/{robot_id}")
async def delete_robot(robot_id: str):
    db = _state["db"]
    rm = _state.get("robot_manager")
    if rm:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, rm.remove, robot_id)
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, svc.queries.list_locations)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/robots/{robot_id}/shelves")
async def get_shelves(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, svc.queries.list_shelves)
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, svc.queries.list_shortcuts)
    except Exception as e:
        raise HTTPException(500, str(e))
