# Chaos Tests

Failure-injection tests against the live Pi + real robot. They prove the
behaviour of high-risk CORNER cases listed in `.sigma/context.md` E2E matrix.

## What they cover

| Test file | CORNER | Batch | Disturbance | Robot motion |
|---|---|---|---|---|
| `test_corner_001_mqtt_down.py` | 001 | 1 | stop mosquitto | none |
| `test_corner_002_stale_command.py` | 002 | 1 | bogus robot IP | possible (1 return_home) |
| `test_corner_004_disconnect_mid_command.py` | 004 | 2 | bogus IP mid-move | yes (move_to_location) |
| `test_corner_013_server_restart_mid_route.py` | 013 | 2 | restart app container | yes (2-stop route) |
| `test_corner_014_robot_disconnect_mid_route.py` | 014 | 2 | bogus IP mid-route | yes (2-stop route) |

## Prerequisites

- SSH key auth to the Pi (test calls `ssh sigma@<pi>` non-interactively)
- The Pi runs the deployed app at `/opt/app/sigma-button-controller`
- Robot is registered in the app and currently online

## Running

```bash
# Batch 1 only — observation, low impact
pytest tests/chaos/ -v -m batch1 \
  --pi-host=192.168.50.5 --robot-ip=192.168.50.169

# Batch 2 — drives the robot, leaves it back at base
pytest tests/chaos/ -v -m batch2 \
  --pi-host=192.168.50.5 --robot-ip=192.168.50.169

# Single test
pytest tests/chaos/test_corner_001_mqtt_down.py -v -s --pi-host=...
```

The `-s` flag is recommended — these tests print observation timelines
inline, which is the actual evidence you want to read.

## Safety

Every test runs through an autouse `safety_finalizer` that:

1. Restarts mosquitto (idempotent)
2. Restores robot IP to the configured value
3. Cancels any in-flight route
4. Drains the queue
5. Waits for the robot to come back online (≤30s)

If a Batch 2 test crashes badly enough that finalizer can't recover,
the robot's own auto-recovery (idle → return home) kicks in after a few
minutes. Worst case: shelf left at a stop, manual return needed.

## Expected results

These tests originally were written to **fail** on the bugs they document
— a failure produces an automated, reproducible record of CORNER-*
behaviour. Status after IT-16 / IT-17 (2026-04-30):

| CORNER | Original failure | Status |
|---|---|---|
| 001 | health/WS expose no MQTT state | **✅ Fixed in IT-16** (MQTT health surface) — chaos 3/3 pass |
| 002 | stale return_home dispatches after reconnect | ✅ Test passes — debounce collapses 3 presses into 1 queue item, 0 stale dispatch |
| 004 | `_executing` only clears after 120s SDK timeout | 🟡 Inconclusive — PATCH IP doesn't sever in-flight gRPC (see ARCH-042); needs network-layer or robot power-cut to drive the bug |
| 013 | run row stuck `running` after restart | **✅ Fixed in IT-17** (rebuild_from_db marks online runs `interrupted`) — chaos pass |
| 014 | route fails when robot disconnects mid-route | 🟡 Inconclusive — same PATCH IP limitation as 004 |

New CORNERs surfaced by this harness:
- **CORNER-027** — `cancel_run` on zombie run silently returns ok but never updated DB → **Fixed in IT-17** (`dispatcher.cancel` always writes DB)
- **CORNER-028** — `rebuild_from_db` resurrected `'running'` rows into `dispatcher.active` → **Fixed in IT-17**

## Adding a new chaos test

1. Pick a CORNER from the matrix that's currently `⬜ unverified`
2. Write a `test_corner_NNN_<name>.py` in this directory
3. Use `pytest.mark.chaos` + `pytest.mark.batch{1,2}`
4. Use the `chaos` fixture (`ChaosOps`) for all I/O
5. Document the disrupt → observe → assert flow in the docstring
