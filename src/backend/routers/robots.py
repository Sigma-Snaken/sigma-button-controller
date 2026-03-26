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
    for row in rows:
        robot_id, name, ip, enabled, created_at = row
        online = False
        battery = None
        serial = None
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
            if svc and svc.conn:
                try:
                    ping = svc.conn.ping()
                    if ping.get("ok"):
                        serial = ping.get("serial")
                except Exception:
                    pass
        result.append({
            "id": robot_id, "name": name, "ip": ip,
            "enabled": bool(enabled), "created_at": created_at,
            "online": online, "battery": battery, "serial": serial,
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
    # Connect to robot immediately
    rm = _state.get("robot_manager")
    connected = False
    if rm:
        try:
            rm.add(robot_id, body.ip.strip())
            connected = True
        except Exception as e:
            logger.warning(f"Robot added to DB but connection failed: {e}")
    return {"ok": True, "id": robot_id, "connected": connected}


@router.put("/robots/{robot_id}")
async def update_robot(robot_id: str, body: RobotUpdate):
    db = _state["db"]
    await db.execute("UPDATE robots SET name = ?, ip = ? WHERE id = ?", (body.name, body.ip, robot_id))
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
        return svc.queries.list_locations()
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
        return svc.queries.list_shelves()
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
        return svc.queries.list_shortcuts()
    except Exception as e:
        raise HTTPException(500, str(e))
