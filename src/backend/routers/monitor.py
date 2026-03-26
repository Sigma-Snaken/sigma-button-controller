from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

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
async def get_camera(robot_id: str, camera: str):
    if camera not in ("front", "back"):
        raise HTTPException(400, "Camera must be 'front' or 'back'")
    rm = _state.get("robot_manager")
    if not rm:
        raise HTTPException(503, "Robot manager not available")
    svc = rm.get(robot_id)
    if not svc or not svc.queries:
        raise HTTPException(404, f"Robot '{robot_id}' not connected")
    try:
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
