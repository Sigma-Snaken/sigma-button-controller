import json
import os
import socket

from fastapi import APIRouter, Request
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.settings")
router = APIRouter()


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


@router.get("/system/info")
async def system_info(request: Request):
    ip = _get_local_ip()
    port = os.environ.get("APP_PORT", "8000")
    return {"ip": ip, "port": port, "url": f"http://{ip}:{port}"}


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
async def update_notify_settings(body: NotifyConfig):
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

    return {"ok": True, "enabled": bool(body.bot_token.strip() and body.chat_id.strip())}


@router.post("/settings/notify/test")
async def test_notify():
    notifier = _state.get("notifier")
    if not notifier or not notifier.enabled:
        return {"ok": False, "error": "Telegram not configured"}
    success = await notifier.send("🔔 Sigma 控制介面通知測試成功！")
    return {"ok": success}


