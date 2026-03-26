"""WiFi management via nmcli."""

import asyncio
import json

from utils.logger import get_logger

logger = get_logger("services.wifi_manager")


async def _run(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode().strip() or stderr.decode().strip()
    return proc.returncode, output


class WifiManager:

    async def status(self) -> dict:
        """Get current WiFi connection status."""
        code, out = await _run([
            "nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,MODE", "dev", "wifi"
        ])
        if code != 0:
            return {"connected": False, "ssid": "", "ip": "", "signal": 0,
                    "mode": "unknown", "error": out}

        ssid, signal, mode = "", 0, "client"
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == "yes":
                ssid = parts[1]
                signal = int(parts[2]) if parts[2].isdigit() else 0
                mode = "ap" if parts[3] == "AP" else "client"
                break

        ip = ""
        if ssid:
            code2, out2 = await _run([
                "nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", "wlan0"
            ])
            if code2 == 0:
                for line in out2.splitlines():
                    if line.startswith("IP4.ADDRESS"):
                        ip = line.split(":", 1)[1].split("/")[0]
                        break

        return {"connected": bool(ssid), "ssid": ssid, "ip": ip,
                "signal": signal, "mode": mode}

    async def scan(self) -> list[dict]:
        """Scan for available WiFi networks."""
        # Trigger rescan
        await _run(["nmcli", "dev", "wifi", "rescan"])
        await asyncio.sleep(2)

        code, out = await _run([
            "nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"
        ])
        if code != 0:
            return []

        networks = []
        seen = set()
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 4:
                continue
            in_use = parts[0] == "*"
            ssid = parts[1]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            signal = int(parts[2]) if parts[2].isdigit() else 0
            security = parts[3] if parts[3] else "Open"
            networks.append({
                "ssid": ssid, "signal": signal,
                "security": security, "in_use": in_use,
            })

        networks.sort(key=lambda n: (-n["in_use"], -n["signal"]))
        return networks

    async def connect_wifi(self, ssid: str, password: str) -> bool:
        """Connect to a WiFi network."""
        # Stop hotspot first if active
        await _run(["nmcli", "dev", "disconnect", "wlan0"])
        await asyncio.sleep(1)

        # Remove any existing profile for this SSID
        await _run(["nmcli", "connection", "delete", ssid])

        if password:
            # Create connection profile with explicit security
            code, out = await _run([
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", "wlan0",
                "con-name", ssid,
                "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password,
            ])
            if code != 0:
                raise RuntimeError(out)
            # Activate it
            code, out = await _run(["nmcli", "connection", "up", ssid])
        else:
            code, out = await _run(["nmcli", "dev", "wifi", "connect", ssid])

        if code != 0:
            logger.error(f"Failed to connect to '{ssid}': {out}")
            raise RuntimeError(out)
        logger.info(f"Connected to '{ssid}'")
        return True

    async def start_hotspot(
        self, ssid: str = "SIGMA-SETUP", password: str = "88888888"
    ) -> bool:
        """Start WiFi AP hotspot."""
        cmd = ["nmcli", "dev", "wifi", "hotspot", "ifname", "wlan0",
               "ssid", ssid]
        if password:
            cmd += ["password", password]

        code, out = await _run(cmd)
        if code != 0:
            logger.error(f"Failed to start hotspot: {out}")
            raise RuntimeError(out)
        logger.info(f"Hotspot '{ssid}' started")
        return True

    async def stop_hotspot(self) -> bool:
        """Stop hotspot and reconnect to previous network."""
        # Disconnect AP
        await _run(["nmcli", "dev", "disconnect", "wlan0"])
        await asyncio.sleep(1)
        # Reconnect to auto network
        code, out = await _run(["nmcli", "dev", "connect", "wlan0"])
        if code != 0:
            logger.error(f"Failed to reconnect: {out}")
            raise RuntimeError(out)
        logger.info("Hotspot stopped, reconnected")
        return True
