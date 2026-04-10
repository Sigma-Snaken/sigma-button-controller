"""Proxy WiFi requests to the host wifi-agent (127.0.0.1:8001)."""

import httpx
from fastapi import APIRouter, Request

router = APIRouter()

import os
AGENT = os.environ.get("WIFI_AGENT_URL", "http://127.0.0.1:8001")


async def _proxy(method: str, path: str, body: dict | None = None):
    async with httpx.AsyncClient(timeout=30) as client:
        if method == "GET":
            resp = await client.get(f"{AGENT}{path}")
        else:
            resp = await client.post(f"{AGENT}{path}", json=body or {})
    return resp.json()


@router.get("/wifi/status")
async def wifi_status():
    return await _proxy("GET", "/status")


@router.post("/wifi/scan")
async def wifi_scan():
    return await _proxy("POST", "/scan")


@router.post("/wifi/connect")
async def wifi_connect(request: Request):
    return await _proxy("POST", "/connect", await request.json())


@router.post("/wifi/hotspot/start")
async def hotspot_start(request: Request):
    body = {}
    if request.headers.get("content-length", "0") != "0":
        body = await request.json()
    return await _proxy("POST", "/hotspot/start", body)


@router.post("/wifi/hotspot/stop")
async def hotspot_stop():
    return await _proxy("POST", "/hotspot/stop")


@router.get("/wifi/connections")
async def wifi_connections():
    return await _proxy("GET", "/connections")


@router.post("/wifi/autoconnect")
async def wifi_autoconnect(request: Request):
    return await _proxy("POST", "/autoconnect", await request.json())


@router.post("/wifi/connection/delete")
async def wifi_delete_connection(request: Request):
    return await _proxy("POST", "/connection/delete", await request.json())
