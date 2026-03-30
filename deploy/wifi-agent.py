#!/usr/bin/env python3
"""Minimal WiFi management agent. Runs on host, exposes nmcli via HTTP.
No pip dependencies — stdlib only.
"""

import asyncio
import json
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse


async def run(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, (stdout or stderr).decode().strip()


async def wifi_status():
    code, out = await run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,MODE", "dev", "wifi"])
    if code != 0:
        return {"connected": False, "ssid": "", "ip": "", "signal": 0, "mode": "unknown", "error": out}
    ssid, signal, mode = "", 0, "client"
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] == "yes":
            ssid, signal = parts[1], int(parts[2]) if parts[2].isdigit() else 0
            mode = "ap" if parts[3] == "AP" else "client"
            break
    ip = ""
    if ssid:
        _, out2 = await run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", "wlan0"])
        for line in out2.splitlines():
            if line.startswith("IP4.ADDRESS"):
                ip = line.split(":", 1)[1].split("/")[0]
                break
    # Also grab eth0 IP if available
    eth_ip = ""
    _, out3 = await run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", "eth0"])
    for line in (out3 or "").splitlines():
        if line.startswith("IP4.ADDRESS"):
            eth_ip = line.split(":", 1)[1].split("/")[0]
            break
    return {"connected": bool(ssid), "ssid": ssid, "ip": ip, "signal": signal, "mode": mode, "eth_ip": eth_ip}


async def wifi_scan():
    await run(["nmcli", "dev", "wifi", "rescan"])
    await asyncio.sleep(2)
    code, out = await run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if code != 0:
        return {"networks": [], "error": out}
    networks, seen = [], set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        in_use, ssid = parts[0] == "*", parts[1]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        networks.append({
            "ssid": ssid,
            "signal": int(parts[2]) if parts[2].isdigit() else 0,
            "security": parts[3] or "Open",
            "in_use": in_use,
        })
    networks.sort(key=lambda n: (-n["in_use"], -n["signal"]))
    return {"networks": networks}


async def wifi_connect(ssid, password):
    await run(["nmcli", "dev", "disconnect", "wlan0"])
    await asyncio.sleep(1)
    await run(["nmcli", "connection", "delete", ssid])
    if password:
        code, out = await run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password,
        ])
        if code != 0:
            return {"ok": False, "error": out}
        code, out = await run(["nmcli", "connection", "up", ssid])
    else:
        code, out = await run(["nmcli", "dev", "wifi", "connect", ssid])
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "message": f"Connected to {ssid}"}


async def hotspot_start(ssid, password):
    if password:
        cmd = ["nmcli", "dev", "wifi", "hotspot", "ifname", "wlan0",
               "ssid", ssid, "password", password]
        code, out = await run(cmd)
    else:
        # nmcli hotspot always requires password; use connection add for open AP
        await run(["nmcli", "connection", "delete", ssid])
        code, out = await run([
            "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
            "con-name", ssid, "ssid", ssid,
            "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
            "ipv4.method", "shared", "ipv6.method", "disabled",
        ])
        if code != 0:
            return {"ok": False, "error": out}
        code, out = await run(["nmcli", "connection", "up", ssid])
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "message": f"AP started: {ssid}"}


async def hotspot_stop():
    await run(["nmcli", "dev", "disconnect", "wlan0"])
    await asyncio.sleep(1)
    code, out = await run(["nmcli", "dev", "connect", "wlan0"])
    if code != 0:
        return {"ok": False, "error": out}
    return {"ok": True, "message": "AP stopped"}


ROUTES = {
    ("GET", "/status"): lambda _: wifi_status(),
    ("POST", "/scan"): lambda _: wifi_scan(),
    ("POST", "/connect"): lambda b: wifi_connect(b["ssid"], b.get("password", "")),
    ("POST", "/hotspot/start"): lambda b: hotspot_start(b.get("ssid", "SIGMA-SETUP"), b.get("password", "")),
    ("POST", "/hotspot/stop"): lambda _: hotspot_stop(),
}


class Handler(BaseHTTPRequestHandler):
    def _handle(self, method):
        path = urlparse(self.path).path
        handler = ROUTES.get((method, path))
        if not handler:
            self.send_response(404)
            self.end_headers()
            return
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            if length:
                body = json.loads(self.rfile.read(length))
        result = asyncio.run(handler(body))
        payload = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # silent


async def auto_ap_on_boot(timeout=30):
    """Wait for WiFi connection; if none after timeout, start AP."""
    import time
    print(f"Waiting {timeout}s for WiFi connection...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = await wifi_status()
        if status["connected"] and status["mode"] == "client":
            print(f"WiFi connected: {status['ssid']} ({status['ip']})")
            return
        await asyncio.sleep(3)
    print("No WiFi connection — starting AP hotspot (SIGMA-SETUP)")
    await hotspot_start("SIGMA-SETUP", "")


if __name__ == "__main__":
    asyncio.run(auto_ap_on_boot())
    server = HTTPServer(("0.0.0.0", 8001), Handler)
    print("WiFi agent listening on 0.0.0.0:8001")
    server.serve_forever()
