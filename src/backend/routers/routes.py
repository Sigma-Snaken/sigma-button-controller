import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.routes")
router = APIRouter()


# ── Pydantic models ──────────────────────────────────────────────────

class StopItem(BaseModel):
    name: str
    timeout_sec: int | None = None
    confirm_button_id: int | None = None


class TemplateCreate(BaseModel):
    name: str
    stops: list[StopItem]
    default_timeout: int = 120
    pinned_robot_id: str | None = None
    confirm_button_id: int | None = None


class TemplateUpdate(BaseModel):
    name: str
    stops: list[StopItem]
    default_timeout: int = 120
    pinned_robot_id: str | None = None
    confirm_button_id: int | None = None


class DispatchRequest(BaseModel):
    template_id: str | None = None
    stops: list[StopItem] | None = None
    default_timeout: int = 120
    confirm_button_id: int | None = None
    pinned_robot_id: str | None = None


# ── Template CRUD ────────────────────────────────────────────────────

@router.get("/routes/templates")
async def list_templates():
    db = _state["db"]
    async with db.execute(
        "SELECT id, name, stops, default_timeout, pinned_robot_id, "
        "confirm_button_id, created_at FROM route_templates ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0], "name": r[1], "stops": json.loads(r[2]),
            "default_timeout": r[3], "pinned_robot_id": r[4],
            "confirm_button_id": r[5], "created_at": r[6],
        }
        for r in rows
    ]


@router.post("/routes/templates", status_code=201)
async def create_template(body: TemplateCreate):
    db = _state["db"]
    tid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    stops_json = json.dumps([s.model_dump(exclude_none=True) for s in body.stops])
    await db.execute(
        "INSERT INTO route_templates (id, name, stops, default_timeout, "
        "pinned_robot_id, confirm_button_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tid, body.name, stops_json, body.default_timeout,
         body.pinned_robot_id, body.confirm_button_id, now),
    )
    await db.commit()
    return {"ok": True, "id": tid}


@router.put("/routes/templates/{template_id}")
async def update_template(template_id: str, body: TemplateUpdate):
    db = _state["db"]
    stops_json = json.dumps([s.model_dump(exclude_none=True) for s in body.stops])
    cursor = await db.execute(
        "UPDATE route_templates SET name = ?, stops = ?, default_timeout = ?, "
        "pinned_robot_id = ?, confirm_button_id = ? WHERE id = ?",
        (body.name, stops_json, body.default_timeout,
         body.pinned_robot_id, body.confirm_button_id, template_id),
    )
    if cursor.rowcount == 0:
        raise HTTPException(404, f"Template '{template_id}' not found")
    await db.commit()
    return {"ok": True}


@router.delete("/routes/templates/{template_id}")
async def delete_template(template_id: str):
    db = _state["db"]
    cursor = await db.execute(
        "DELETE FROM route_templates WHERE id = ?", (template_id,),
    )
    if cursor.rowcount == 0:
        raise HTTPException(404, f"Template '{template_id}' not found")
    await db.commit()
    return {"ok": True}


# ── Dispatch / Cancel ────────────────────────────────────────────────

@router.post("/routes/dispatch")
async def dispatch_route(body: DispatchRequest):
    dispatcher = _state.get("route_dispatcher")
    if not dispatcher:
        raise HTTPException(503, "Route dispatcher not available")

    kwargs: dict = {
        "default_timeout": body.default_timeout,
        "confirm_button_id": body.confirm_button_id,
        "pinned_robot_id": body.pinned_robot_id,
    }
    if body.template_id:
        kwargs["template_id"] = body.template_id
    if body.stops:
        kwargs["stops"] = [s.model_dump(exclude_none=True) for s in body.stops]

    result = await dispatcher.dispatch(**kwargs)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Dispatch failed"))
    return result


@router.post("/routes/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    dispatcher = _state.get("route_dispatcher")
    if not dispatcher:
        raise HTTPException(503, "Route dispatcher not available")
    result = await dispatcher.cancel(run_id)
    if not result.get("ok"):
        raise HTTPException(404, result.get("error", "Run not found"))
    return result


# ── Runs ─────────────────────────────────────────────────────────────

@router.get("/routes/runs")
async def list_active_runs():
    db = _state["db"]
    async with db.execute(
        "SELECT id, template_id, robot_id, stops, default_timeout, "
        "confirm_button_id, status, current_stop, started_at "
        "FROM route_runs WHERE status IN ('queued', 'assigned', 'running') "
        "ORDER BY started_at"
    ) as cursor:
        rows = await cursor.fetchall()

    route_service = _state.get("route_service")
    active = route_service.get_active_runs() if route_service else {}

    result = []
    for r in rows:
        run_id = r[0]
        entry = {
            "id": run_id, "template_id": r[1], "robot_id": r[2],
            "stops": json.loads(r[3]), "default_timeout": r[4],
            "confirm_button_id": r[5], "status": r[6],
            "current_stop": r[7], "started_at": r[8],
        }
        if run_id in active:
            entry.update(active[run_id])
        result.append(entry)
    return result


@router.get("/routes/runs/{run_id}")
async def get_run(run_id: str):
    db = _state["db"]
    async with db.execute(
        "SELECT id, template_id, robot_id, stops, default_timeout, "
        "confirm_button_id, status, current_stop, started_at, completed_at "
        "FROM route_runs WHERE id = ?",
        (run_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, f"Run '{run_id}' not found")

    async with db.execute(
        "SELECT stop_index, location_name, arrived_at, confirmed_at, "
        "confirmed_by, timed_out, departed_at "
        "FROM route_stop_logs WHERE run_id = ? ORDER BY stop_index",
        (run_id,),
    ) as cursor:
        log_rows = await cursor.fetchall()

    stop_logs = [
        {
            "stop_index": lr[0], "location_name": lr[1],
            "arrived_at": lr[2], "confirmed_at": lr[3],
            "confirmed_by": lr[4], "timed_out": bool(lr[5]),
            "departed_at": lr[6],
        }
        for lr in log_rows
    ]

    return {
        "id": row[0], "template_id": row[1], "robot_id": row[2],
        "stops": json.loads(row[3]), "default_timeout": row[4],
        "confirm_button_id": row[5], "status": row[6],
        "current_stop": row[7], "started_at": row[8],
        "completed_at": row[9], "stop_logs": stop_logs,
    }


# ── History ──────────────────────────────────────────────────────────

@router.get("/routes/history")
async def history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    db = _state["db"]
    offset = (page - 1) * per_page

    async with db.execute(
        "SELECT COUNT(*) FROM route_runs "
        "WHERE status IN ('completed', 'cancelled', 'failed')"
    ) as cursor:
        total = (await cursor.fetchone())[0]

    async with db.execute(
        "SELECT id, template_id, robot_id, stops, default_timeout, "
        "status, current_stop, started_at, completed_at "
        "FROM route_runs WHERE status IN ('completed', 'cancelled', 'failed') "
        "ORDER BY completed_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    ) as cursor:
        rows = await cursor.fetchall()

    runs = [
        {
            "id": r[0], "template_id": r[1], "robot_id": r[2],
            "stops": json.loads(r[3]), "default_timeout": r[4],
            "status": r[5], "current_stop": r[6],
            "started_at": r[7], "completed_at": r[8],
        }
        for r in rows
    ]

    return {"runs": runs, "total": total, "page": page, "per_page": per_page}


# ── Dispatcher status ────────────────────────────────────────────────

@router.get("/routes/dispatcher/status")
async def dispatcher_status():
    dispatcher = _state.get("route_dispatcher")
    if not dispatcher:
        raise HTTPException(503, "Route dispatcher not available")
    return dispatcher.get_status()
