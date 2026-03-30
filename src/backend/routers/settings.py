import json
import os

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.settings")
router = APIRouter()


@router.get("/system/info")
async def system_info(request: Request):
    wifi_url = os.environ.get("WIFI_AGENT_URL", "http://host.docker.internal:8001")
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{wifi_url}/status")
            ip = resp.json().get("ip")
            if ip:
                return {"host": ip, "url": f"http://{ip}:8000"}
    except Exception:
        pass
    # Fallback to request host header
    host = request.headers.get("host", "unknown")
    return {"host": host, "url": f"http://{host}"}


@router.get("/settings/notify")
async def get_notify_settings():
    db = _state["db"]
    result = {"bot_token": "", "chat_id": "", "enabled": False}
    async with db.execute(
        "SELECT value FROM settings WHERE key = 'telegram_config'"
    ) as cursor:
        row = await cursor.fetchone()
    if row:
        try:
            config = json.loads(row[0])
            result["bot_token"] = config.get("bot_token", "")
            result["chat_id"] = config.get("chat_id", "")
            result["enabled"] = bool(result["bot_token"] and result["chat_id"])
        except json.JSONDecodeError:
            pass
    return result


class NotifyConfig(BaseModel):
    bot_token: str
    chat_id: str


@router.put("/settings/notify")
async def update_notify_settings(body: NotifyConfig, request: Request):
    db = _state["db"]
    config = json.dumps({"bot_token": body.bot_token.strip(), "chat_id": body.chat_id.strip()})
    await db.execute(
        "INSERT INTO settings (key, value) VALUES ('telegram_config', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (config,),
    )
    await db.commit()

    # Update notifier
    notifier = _state.get("notifier")
    if notifier:
        notifier.configure(body.bot_token, body.chat_id)
        notifier.host_url = f"http://{request.headers.get('host', 'unknown')}"

    return {"ok": True, "enabled": bool(body.bot_token.strip() and body.chat_id.strip())}


@router.post("/settings/notify/test")
async def test_notify(request: Request):
    notifier = _state.get("notifier")
    if not notifier or not notifier.enabled:
        return {"ok": False, "error": "Telegram not configured"}
    host = request.headers.get("host", "unknown")
    success = await notifier.send(f"🔔 Sigma 控制介面通知測試成功！\n📍 http://{host}")
    return {"ok": success}


