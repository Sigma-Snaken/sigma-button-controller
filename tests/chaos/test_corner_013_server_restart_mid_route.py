"""
CORNER-013: app server restart mid-route → robot stranded with shelf.

Scenario:
  A multi-stop route is running. The app container is restarted.
  The route_run row may be left in `running` status forever (zombie).
  The robot, meanwhile, may still be physically holding/carrying a shelf.

Pass criteria:
  - On restart, route_run rows previously in 'running' must NOT remain 'running'.
    Acceptable terminal states: failed, cancelled, or interrupted.
  - The DB rebuild at startup should detect orphaned runs.

Likely outcome: PROBABLY FAIL — `rebuild_from_db` (per ARCH-035) only handles
offline_running cleanup, not online routes.
"""
import time

import pytest


pytestmark = [pytest.mark.chaos, pytest.mark.batch2]


@pytest.fixture
def online_route_mode(chaos):
    """Force online route mode for the test, restore original after."""
    original = chaos.get_route_mode()
    if original != "online":
        chaos.set_route_mode("online")
    yield
    if original and original != "online":
        chaos.set_route_mode(original)


@pytest.fixture
def temp_route(chaos):
    """Create a 2-stop route template, yield its id, delete on teardown."""
    import httpx
    with httpx.Client(timeout=10) as c:
        loc = c.get(f"{chaos.base_url}/api/robots/{chaos.robot_id}/locations").json()
    locations = [l for l in loc.get("locations", []) if l.get("type") == "0"]
    assert len(locations) >= 2, f"Need ≥2 type-0 locations, got {len(locations)}"
    stops = [{"name": locations[0]["name"], "timeout_sec": 30},
             {"name": locations[1]["name"], "timeout_sec": 30}]
    print(f"\n[setup] route stops: {[s['name'] for s in stops]}")

    res = chaos.create_template(
        name=f"chaos-013-{int(time.time())}",
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


def test_server_restart_mid_route_no_zombie_run(chaos, online_route_mode, temp_route):
    template_id = temp_route

    assert chaos.wait_robot_online(timeout=15)

    # 1. Dispatch route
    print(f"\n[step 1] dispatch route template {template_id}")
    res = chaos.dispatch_route(template_id=template_id)
    print(f"[step 1] dispatch result: {res}")
    run_id = res.get("run_id") or res.get("id")
    assert run_id, f"No run_id in dispatch response: {res}"

    # 2. Wait until running (robot starts moving to first stop)
    waited = 0
    for sec in range(30):
        time.sleep(1)
        waited = sec + 1
        run = chaos.get_run(run_id)
        if run and run.get("status") == "running":
            print(f"[step 2] route is running after {waited}s, "
                  f"current_stop={run.get('current_stop')}")
            break
    else:
        pytest.fail(f"Route did not enter 'running' state in {waited}s")

    # Give it 5 more seconds in motion
    time.sleep(5)

    # 3. Restart the app container mid-flight
    print(f"\n[step 3] docker compose restart app (mid-route)")
    rc, out, err = chaos.restart_app()
    print(f"[step 3] restart rc={rc}")

    # 4. Wait for app to come back
    assert chaos.wait_app_healthy(timeout=45), "App did not come back after restart"
    print(f"[step 4] app healthy")
    time.sleep(3)

    # 5. Inspect run state
    run_after = chaos.get_run(run_id)
    print(f"\n[step 5] run state after restart: {run_after.get('status') if run_after else None}")
    print(f"  full: {run_after}")

    # Pass = run is in a terminal state, not 'running' zombie
    assert run_after is not None, f"Run {run_id} disappeared from DB"
    status = run_after.get("status")
    assert status not in ("running", "queued", "assigned"), (
        f"BUG: run {run_id} is still {status!r} after app restart. "
        f"It should be one of: failed, cancelled, interrupted (CORNER-013). "
        f"This means the robot is physically moving but no service is tracking it."
    )
