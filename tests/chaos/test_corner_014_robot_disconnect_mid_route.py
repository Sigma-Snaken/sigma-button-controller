"""
CORNER-014: robot disconnects mid-route → SDK retry chain → eventual move timeout.

Scenario:
  A 2-stop route is running. While moving to stop 1, robot connection breaks.
  SDK has a 5-layer retry. Eventually move_to_location hits 120s timeout
  and the route should be marked failed. Shelf may not return.

Pass criteria:
  - Route status should reach `failed` within ~3 minutes of disconnect.
  - Route should not hang in `running` indefinitely.

Likely outcome: PASS (eventually) — SDK timeout exists. The question is HOW LONG.
"""
import time

import pytest

from .conftest import BOGUS_IP


pytestmark = [pytest.mark.chaos, pytest.mark.batch2]


@pytest.fixture
def online_route_mode(chaos):
    original = chaos.get_route_mode()
    if original != "online":
        chaos.set_route_mode("online")
    yield
    if original and original != "online":
        chaos.set_route_mode(original)


@pytest.fixture
def temp_route(chaos):
    import httpx
    with httpx.Client(timeout=10) as c:
        loc = c.get(f"{chaos.base_url}/api/robots/{chaos.robot_id}/locations").json()
    locations = [l for l in loc.get("locations", []) if l.get("type") == "0"]
    assert len(locations) >= 2, f"Need ≥2 type-0 locations, got {len(locations)}"
    stops = [{"name": locations[0]["name"], "timeout_sec": 30},
             {"name": locations[1]["name"], "timeout_sec": 30}]
    res = chaos.create_template(
        name=f"chaos-014-{int(time.time())}",
        stops=stops,
        default_timeout=30,
        pinned_robot_id=chaos.robot_id,
    )
    tid = res["id"]
    yield tid
    try:
        chaos.delete_template(tid)
    except Exception:
        pass


def test_robot_disconnect_mid_route_eventually_fails(chaos, online_route_mode, temp_route):
    template_id = temp_route

    assert chaos.wait_robot_online(timeout=15)

    # 1. Dispatch
    print(f"\n[step 1] dispatch route")
    res = chaos.dispatch_route(template_id=template_id)
    run_id = res.get("run_id") or res.get("id")
    assert run_id

    # 2. Wait until running
    for _ in range(30):
        time.sleep(1)
        run = chaos.get_run(run_id)
        if run and run.get("status") == "running":
            print(f"[step 2] running, current_stop={run.get('current_stop')}")
            break
    else:
        pytest.fail("Route never entered running state")

    time.sleep(3)

    # 3. Disconnect
    disconnect_at = time.time()
    print(f"\n[step 3] PATCH robot IP -> {BOGUS_IP}")
    chaos.patch_robot_ip(BOGUS_IP)

    # 4. Watch for terminal state, max 240s (SDK timeout 120s + buffer)
    final_status = None
    for sec in range(240):
        time.sleep(1)
        run = chaos.get_run(run_id)
        if run is None:
            print(f"[step 4] run disappeared at t+{sec+1}s")
            break
        st = run.get("status")
        if st not in ("running", "queued", "assigned"):
            final_status = st
            print(f"[step 4] terminal status '{st}' reached at t+{sec+1}s")
            break
        if sec % 30 == 0:
            print(f"  t+{sec}s: status={st}, current_stop={run.get('current_stop')}")

    elapsed = time.time() - disconnect_at
    print(f"\n[result] route reached terminal state '{final_status}' "
          f"in {elapsed:.1f}s after disconnect")

    assert final_status in ("failed", "cancelled"), (
        f"BUG: route did not reach terminal state after disconnect. "
        f"Final status: {final_status} after {elapsed:.0f}s (CORNER-014)"
    )
    assert elapsed < 180, (
        f"SLOW: route took {elapsed:.0f}s to fail after disconnect. "
        f"Expected <3min. Consider tighter health checks."
    )
