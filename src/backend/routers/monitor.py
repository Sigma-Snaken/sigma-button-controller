from fastapi import APIRouter, HTTPException

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
        map_data = svc.queries.get_map()
        pose_data = svc.queries.get_pose()
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
            "pose": {
                "x": pose_data.get("x"),
                "y": pose_data.get("y"),
                "theta": pose_data.get("theta"),
            } if pose_data.get("ok") else None,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/robots/{robot_id}/camera/{camera}")
async def get_camera(robot_id: str, camera: str, detect: bool = False):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        # Use CameraStreamer if running, otherwise direct query
        streamer = svc.front_streamer if camera == "front" else svc.back_streamer
        if streamer and streamer.is_running:
            frame = streamer.latest_frame
            if frame and frame.get("ok"):
                result = {
                    "ok": True,
                    "image_base64": frame.get("image_base64"),
                    "format": frame.get("format", "jpeg"),
                }
                if detect:
                    result["objects"] = streamer.latest_detections or []
                return result

        # Fallback: direct capture
        if detect and svc.detector:
            img = svc.detector.capture_with_detections(camera=camera)
            return {
                "ok": True,
                "image_base64": img.get("image_base64"),
                "format": img.get("format", "jpeg"),
                "objects": img.get("objects", []),
            }
        else:
            if camera == "front":
                img = svc.queries.get_front_camera_image()
            else:
                img = svc.queries.get_back_camera_image()
            return {
                "ok": True,
                "image_base64": img.get("image_base64"),
                "format": img.get("format", "jpeg"),
            }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/robots/{robot_id}/streamer/{camera}")
async def start_streamer(robot_id: str, camera: str, detect: bool = False):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
        svc.start_streamer(camera, detect=detect)
        return {"ok": True, "camera": camera, "detect": detect}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/robots/{robot_id}/streamer/{camera}")
async def stop_streamer(robot_id: str, camera: str):
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


@router.get("/robots/{robot_id}/detections")
async def get_detections(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    if not svc.detector:
        raise HTTPException(503, "Object detector not available")
    try:
        result = svc.detector.get_detections()
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/robots/{robot_id}/metrics")
async def get_metrics(robot_id: str):
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")

    result = {"ok": True}

    # Controller metrics
    if svc.controller:
        try:
            m = svc.controller.metrics
            rtt_list = m.poll_rtt_list if hasattr(m, 'poll_rtt_list') else []
            result["controller"] = {
                "poll_count": m.poll_count if hasattr(m, 'poll_count') else 0,
                "avg_rtt_ms": round(sum(rtt_list) / len(rtt_list), 1) if rtt_list else 0,
                "max_rtt_ms": round(max(rtt_list), 1) if rtt_list else 0,
            }
        except Exception:
            result["controller"] = None

    # CameraStreamer stats
    for cam_name, streamer in [("front", svc.front_streamer), ("back", svc.back_streamer)]:
        if streamer and streamer.is_running:
            try:
                stats = streamer.stats
                result[f"{cam_name}_camera"] = {
                    "total_frames": stats.get("total_frames", 0),
                    "dropped": stats.get("dropped", 0),
                    "drop_rate_pct": stats.get("drop_rate_pct", 0),
                    "running": True,
                }
            except Exception:
                result[f"{cam_name}_camera"] = {"running": True}
        else:
            result[f"{cam_name}_camera"] = {"running": False}

    return result
