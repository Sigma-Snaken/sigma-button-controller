import asyncio

from fastapi import APIRouter, HTTPException, Query

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.monitor")
router = APIRouter()


@router.get("/robots/{robot_id}/map")
async def get_map(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        # Map is sync gRPC — run in thread to avoid blocking event loop
        loop = asyncio.get_event_loop()
        map_data = await loop.run_in_executor(None, svc.queries.get_map)

        # Pose from controller.state (non-blocking, already polled in background)
        pose = None
        if svc.controller:
            state = svc.controller.state
            if state and getattr(state, 'pose_x', None) is not None:
                pose = {
                    "x": state.pose_x,
                    "y": state.pose_y,
                    "theta": state.pose_theta,
                }

        return {
            "ok": True,
            "map": {
                "image_base64": map_data.get("image_base64"),
                "format": map_data.get("format", "png"),
                "resolution": map_data.get("resolution"),
                "width": map_data.get("width"),
                "height": map_data.get("height"),
                "origin_x": map_data.get("origin_x"),
                "origin_y": map_data.get("origin_y"),
            },
            "pose": pose,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/robots/{robot_id}/camera/{camera}")
async def get_camera(robot_id: str, camera: str):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    streamer = svc.front_streamer if camera == "front" else svc.back_streamer
    if not streamer or not streamer.is_running:
        raise HTTPException(404, "Camera streamer not running. Start it first.")
    frame = streamer.latest_frame
    if not frame or not frame.get("ok"):
        raise HTTPException(503, "No frame available yet")
    return {
        "ok": True,
        "image_base64": frame.get("image_base64"),
        "format": frame.get("format", "jpeg"),
    }


@router.post("/robots/{robot_id}/camera/{camera}/start")
async def start_camera(robot_id: str, camera: str):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    svc.start_streamer(camera)
    return {"ok": True}


@router.post("/robots/{robot_id}/camera/{camera}/stop")
async def stop_camera(robot_id: str, camera: str):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    svc.stop_streamer(camera)
    return {"ok": True}


@router.get("/robots/{robot_id}/metrics")
async def get_metrics(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")

    result = {"ok": True}

    if svc.controller:
        try:
            m = svc.controller.metrics
            rtt_list = m.poll_rtt_list if hasattr(m, 'poll_rtt_list') else []
            result["controller"] = {
                "poll_count": m.poll_count if hasattr(m, 'poll_count') else 0,
                "avg_rtt_ms": round(sum(rtt_list) / len(rtt_list), 1) if rtt_list else 0,
                "max_rtt_ms": round(max(rtt_list), 1) if rtt_list else 0,
                "latest_rtt_ms": round(rtt_list[-1], 1) if rtt_list else 0,
            }
        except Exception:
            result["controller"] = None

    return result


@router.get("/robots/{robot_id}/rtt-heatmap")
async def get_rtt_heatmap(robot_id: str, limit: int = Query(500, ge=1, le=5000)):
    """Return RTT data points for heatmap overlay on map."""
    db = _state.get("db")
    if not db:
        raise HTTPException(503, "Database not available")
    async with db.execute(
        "SELECT x, y, rtt_ms, battery, recorded_at FROM rtt_logs "
        "WHERE robot_name = ? ORDER BY id DESC LIMIT ?",
        (robot_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    points = [
        {"x": r[0], "y": r[1], "rtt_ms": r[2], "battery": r[3], "t": r[4]}
        for r in rows
    ]
    # Compute stats
    if points:
        rtts = [p["rtt_ms"] for p in points]
        stats = {
            "count": len(points),
            "avg_rtt_ms": round(sum(rtts) / len(rtts), 1),
            "min_rtt_ms": round(min(rtts), 1),
            "max_rtt_ms": round(max(rtts), 1),
        }
    else:
        stats = {"count": 0, "avg_rtt_ms": 0, "min_rtt_ms": 0, "max_rtt_ms": 0}
    return {"ok": True, "points": points, "stats": stats}


@router.delete("/robots/{robot_id}/rtt-heatmap")
async def clear_rtt_heatmap(robot_id: str):
    """Clear RTT data for a robot."""
    db = _state.get("db")
    if not db:
        raise HTTPException(503, "Database not available")
    await db.execute("DELETE FROM rtt_logs WHERE robot_name = ?", (robot_id,))
    await db.commit()
    return {"ok": True}
