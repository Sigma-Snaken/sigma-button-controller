"""
Chaos test fixtures: real Pi + real robot, deliberate failure injection.

Run:
    pytest tests/chaos/ -v -m chaos --pi-host=192.168.50.5 --robot-ip=192.168.50.169

Each test gets an autouse `safety_finalizer` that restores mosquitto, robot IP,
and clears any active route + queue, even if the test crashes.
"""
import json
import subprocess
import time

import httpx
import pytest

PI_USER = "sigma"
DEFAULT_PI_HOST = "192.168.50.5"
DEFAULT_ROBOT_IP = "192.168.50.169"
DEFAULT_ROBOT_ID = "Pro-7"
APP_DIR = "/opt/app/sigma-button-controller"
MOSQUITTO_CONTAINER = "sigma-button-controller-mosquitto-1"
APP_CONTAINER = "sigma-button-controller-app-1"
BOGUS_IP = "192.168.50.254"


def pytest_addoption(parser):
    parser.addoption("--pi-host", default=DEFAULT_PI_HOST,
                     help="Pi IP running the deployed app")
    parser.addoption("--robot-ip", default=DEFAULT_ROBOT_IP,
                     help="Real robot IP")
    parser.addoption("--robot-id", default=DEFAULT_ROBOT_ID,
                     help="Robot id registered in the app DB")


def pytest_configure(config):
    config.addinivalue_line("markers", "chaos: deliberate failure injection on real Pi+robot")
    config.addinivalue_line("markers", "batch1: observation only — no robot motion")
    config.addinivalue_line("markers", "batch2: drives robot, may interrupt routes")


@pytest.fixture(scope="session")
def pi_host(request):
    return request.config.getoption("--pi-host")


@pytest.fixture(scope="session")
def robot_ip(request):
    return request.config.getoption("--robot-ip")


@pytest.fixture(scope="session")
def robot_id(request):
    return request.config.getoption("--robot-id")


@pytest.fixture(scope="session")
def base_url(pi_host):
    return f"http://{pi_host}:8000"


@pytest.fixture(scope="session")
def ws_url(pi_host):
    return f"ws://{pi_host}:8000/ws"


class ChaosOps:
    """All disruption + observation primitives. Designed to be idempotent and crash-safe."""

    def __init__(self, pi_host, base_url, robot_id, robot_ip):
        self.pi_host = pi_host
        self.base_url = base_url
        self.robot_id = robot_id
        self.robot_ip = robot_ip

    # ── SSH primitive ──────────────────────────────────────────────────
    def ssh(self, cmd, timeout=30):
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             f"{PI_USER}@{self.pi_host}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    # ── Disruption: MQTT ───────────────────────────────────────────────
    def stop_mosquitto(self):
        return self.ssh(f"cd {APP_DIR} && docker compose stop mosquitto")

    def start_mosquitto(self):
        return self.ssh(f"cd {APP_DIR} && docker compose start mosquitto")

    def mosquitto_running(self) -> bool:
        rc, out, _ = self.ssh(
            f"docker inspect -f '{{{{.State.Running}}}}' {MOSQUITTO_CONTAINER}")
        return rc == 0 and out == "true"

    # ── Disruption: app ────────────────────────────────────────────────
    def restart_app(self):
        return self.ssh(f"cd {APP_DIR} && docker compose restart app")

    def app_logs(self, n=200):
        rc, out, _ = self.ssh(f"docker logs --tail={n} {APP_CONTAINER} 2>&1")
        return out if rc == 0 else ""

    def wait_app_healthy(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if httpx.get(f"{self.base_url}/api/health", timeout=3).status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    # ── Disruption: robot connection (no sudo needed) ──────────────────
    def patch_robot_ip(self, new_ip):
        with httpx.Client(timeout=10) as c:
            r = c.put(
                f"{self.base_url}/api/robots/{self.robot_id}",
                json={"name": self.robot_id, "ip": new_ip},
            )
            r.raise_for_status()
            return r.json()

    def restore_robot_ip(self):
        return self.patch_robot_ip(self.robot_ip)

    # ── Trigger: button via Pi-side mosquitto ──────────────────────────
    def fire_button(self, ieee, action="single"):
        payload = json.dumps({"action": action})
        cmd = (f"docker exec {MOSQUITTO_CONTAINER} "
               f"mosquitto_pub -h localhost -t 'zigbee2mqtt/{ieee}' "
               f"-m '{payload}'")
        return self.ssh(cmd)

    # ── Observation: HTTP API ──────────────────────────────────────────
    def get_health(self):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/health").json()

    def get_robots(self):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/robots").json()

    def get_robot(self):
        return next((r for r in self.get_robots() if r["id"] == self.robot_id), None)

    def get_queue(self):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/queue").json()

    def cancel_queue(self):
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{self.base_url}/api/queue/cancel/{self.robot_id}")
            return r.json() if r.status_code < 500 else {"ok": False}

    # ── Routes ─────────────────────────────────────────────────────────
    def create_template(self, name, stops, **kw):
        body = {"name": name, "stops": stops}
        body.update(kw)
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{self.base_url}/api/routes/templates", json=body)
            r.raise_for_status()
            return r.json()

    def delete_template(self, tid):
        with httpx.Client(timeout=10) as c:
            return c.delete(f"{self.base_url}/api/routes/templates/{tid}").json()

    def dispatch_route(self, **kw):
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{self.base_url}/api/routes/dispatch", json=kw)
            r.raise_for_status()
            return r.json()

    def list_active_runs(self):
        with httpx.Client(timeout=10) as c:
            return c.get(f"{self.base_url}/api/routes/runs").json()

    def get_run(self, run_id):
        with httpx.Client(timeout=10) as c:
            r = c.get(f"{self.base_url}/api/routes/runs/{run_id}")
            return r.json() if r.status_code == 200 else None

    def cancel_run(self, run_id):
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{self.base_url}/api/routes/runs/{run_id}/cancel")
            return r.json() if r.status_code < 500 else {"ok": False}

    # ── Bindings ──────────────────────────────────────────────────────
    def set_binding(self, button_id, trigger, action, params=None):
        body = {trigger: {"robot_id": self.robot_id, "action": action,
                          "params": params or {}}}
        with httpx.Client(timeout=10) as c:
            r = c.put(f"{self.base_url}/api/bindings/{button_id}", json=body)
            r.raise_for_status()
            return r.json()

    def clear_binding(self, button_id):
        with httpx.Client(timeout=10) as c:
            return c.put(
                f"{self.base_url}/api/bindings/{button_id}",
                json={"single": None, "double": None, "long": None},
            ).json()

    def get_binding(self, button_id):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/bindings/{button_id}").json()

    def get_buttons(self):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/buttons").json()

    # ── Settings ──────────────────────────────────────────────────────
    def get_route_mode(self):
        with httpx.Client(timeout=5) as c:
            return c.get(f"{self.base_url}/api/settings/route-mode").json().get("mode")

    def set_route_mode(self, mode):
        with httpx.Client(timeout=10) as c:
            r = c.put(f"{self.base_url}/api/settings/route-mode", json={"mode": mode})
            r.raise_for_status()
            return r.json()

    # ── Wait helpers ──────────────────────────────────────────────────
    def wait_robot_online(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                r = self.get_robot()
                if r and r.get("online") and r.get("connection_state") == "connected":
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False


@pytest.fixture
def chaos(pi_host, base_url, robot_id, robot_ip):
    return ChaosOps(pi_host, base_url, robot_id, robot_ip)


@pytest.fixture(autouse=True)
def safety_finalizer(chaos):
    """Best-effort restore: mosquitto up, robot IP correct, no in-flight route, queue drained."""
    yield

    errors = []

    # 1. Restart mosquitto if down
    try:
        if not chaos.mosquitto_running():
            chaos.start_mosquitto()
            time.sleep(2)
    except Exception as e:
        errors.append(f"mosquitto restart: {e}")

    # 2. Wait for app (in case a test restarted it)
    try:
        chaos.wait_app_healthy(timeout=30)
    except Exception as e:
        errors.append(f"app health wait: {e}")

    # 3. Restore robot IP if changed
    try:
        r = chaos.get_robot()
        if r and r.get("ip") != chaos.robot_ip:
            chaos.restore_robot_ip()
            time.sleep(2)
    except Exception as e:
        errors.append(f"robot IP restore: {e}")

    # 4. Cancel any active route
    try:
        for run in chaos.list_active_runs():
            rid = run.get("id")
            if rid:
                chaos.cancel_run(rid)
    except Exception as e:
        errors.append(f"route cancel: {e}")

    # 5. Drain queue
    try:
        chaos.cancel_queue()
    except Exception as e:
        errors.append(f"queue cancel: {e}")

    # 6. Wait for robot to come back online (max 30s)
    try:
        chaos.wait_robot_online(timeout=30)
    except Exception:
        pass

    if errors:
        print(f"\n[safety_finalizer] cleanup errors: {errors}")
