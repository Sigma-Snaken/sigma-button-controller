import json
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from main import _state
from utils.logger import get_logger

logger = get_logger("routers.settings")
router = APIRouter()


async def _get_setting(key: str, default: str = "") -> str:
    db = _state["db"]
    async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else default


async def _set_setting(key: str, value: str) -> None:
    db = _state["db"]
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


@router.get("/system/info")
async def system_info(request: Request):
    wifi_url = os.environ.get("WIFI_AGENT_URL", "http://host.docker.internal:8001")
    wifi_ip = ""
    eth_ip = ""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{wifi_url}/status")
            data = resp.json()
            wifi_ip = data.get("ip", "")
            eth_ip = data.get("eth_ip", "")
    except Exception:
        pass
    # Primary IP: prefer wifi, fallback to eth, then request header
    ip = wifi_ip or eth_ip or request.headers.get("host", "unknown").split(":")[0]
    return {"host": ip, "url": f"http://{ip}:8000", "wifi_ip": wifi_ip, "eth_ip": eth_ip}


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


class ToggleConfig(BaseModel):
    enabled: bool


@router.get("/settings/rtt-logger")
async def get_rtt_logger_settings():
    return {"enabled": (await _get_setting("rtt_logger_enabled", "true")) == "true"}


@router.put("/settings/rtt-logger")
async def update_rtt_logger_settings(body: ToggleConfig):
    await _set_setting("rtt_logger_enabled", "true" if body.enabled else "false")
    rtt_logger = _state.get("rtt_logger")
    if rtt_logger:
        rtt_logger.set_enabled(body.enabled)
    return {"ok": True, "enabled": body.enabled}


@router.get("/settings/queue")
async def get_queue_settings():
    return {"enabled": (await _get_setting("queue_enabled", "true")) == "true"}


@router.put("/settings/queue")
async def update_queue_settings(body: ToggleConfig):
    await _set_setting("queue_enabled", "true" if body.enabled else "false")
    queue = _state.get("command_queue")
    if queue:
        queue.set_enabled(body.enabled)
    return {"ok": True, "enabled": body.enabled}


@router.get("/settings/route-mode")
async def get_route_mode():
    return {"mode": await _get_setting("route_mode", "online")}


class RouteModeConfig(BaseModel):
    mode: str  # "online" or "offline"


@router.put("/settings/route-mode")
async def update_route_mode(body: RouteModeConfig):
    if body.mode not in ("online", "offline"):
        raise HTTPException(400, "Mode must be 'online' or 'offline'")
    await _set_setting("route_mode", body.mode)
    dispatcher = _state.get("route_dispatcher")
    if dispatcher:
        dispatcher.set_route_mode(body.mode)
    return {"ok": True, "mode": body.mode}


@router.get("/settings/pi-url")
async def get_pi_url():
    return {"url": await _get_setting("pi_url")}


class PiUrlConfig(BaseModel):
    url: str


@router.put("/settings/pi-url")
async def update_pi_url(body: PiUrlConfig):
    url = body.url.strip().rstrip("/")
    if url and not url.startswith("http"):
        url = f"http://{url}"
    await _set_setting("pi_url", url)
    dispatcher = _state.get("route_dispatcher")
    if dispatcher:
        dispatcher.set_pi_url(url)
    return {"ok": True, "url": url}


