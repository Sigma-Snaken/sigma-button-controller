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

These tests are written to **fail** on the bugs they document. A failure
here is success — it produces an automated, reproducible record of
CORNER-* behaviour. Use the failures to drive new iterations:

| CORNER | Likely fail | Iteration to open |
|---|---|---|
| 001 | health/WS expose no MQTT state | IT-15: MQTT health surface |
| 002 | 3 stale return_home dispatches after reconnect | IT-16: queue stale-command policy |
| 004 | _executing only clears after 120s SDK timeout | IT-17: faster disconnect detection |
| 013 | run row stuck `running` after restart | IT-18: route rebuild_from_db for online runs |
| 014 | (likely passes — measures how long) | document the timing, possibly tighten |

## Adding a new chaos test

1. Pick a CORNER from the matrix that's currently `⬜ unverified`
2. Write a `test_corner_NNN_<name>.py` in this directory
3. Use `pytest.mark.chaos` + `pytest.mark.batch{1,2}`
4. Use the `chaos` fixture (`ChaosOps`) for all I/O
5. Document the disrupt → observe → assert flow in the docstring
