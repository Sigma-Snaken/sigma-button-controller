"""
CORNER-004: command not auto-cancelled during robot disconnect.

Scenario:
  Robot is executing move_to_location (blocking SDK call, 120s timeout).
  Mid-flight, the connection breaks (we PATCH the IP to bogus).
  The command keeps blocking until SDK timeout — meanwhile state is desynced.

Pass criteria:
  - command should NOT remain `executing` for the full 120s SDK timeout
  - either the queue notices and cancels, or a connection_state event fires
  - `_executing[robot_id]` should clear within ~30s of disconnect

Likely outcome: PARTIAL — `_executing` only clears after SDK times out (~120s).
"""
import time

import pytest

from .conftest import BOGUS_IP


pytestmark = [pytest.mark.chaos, pytest.mark.batch2]

BUTTON_IEEE = "0x08ddebfffea3a363"
BUTTON_ID = 5


@pytest.fixture
def with_move_binding(chaos):
    """button 5 single → move_to_location to b1."""
    original = chaos.get_binding(BUTTON_ID)
    # Find a real location to move to
    import httpx
    with httpx.Client(timeout=10) as c:
        loc = c.get(f"{chaos.base_url}/api/robots/{chaos.robot_id}/locations").json()
    locations = loc.get("locations", [])
    target = next((l["name"] for l in locations if l.get("type") == "0"), None)
    assert target, "No type=0 location to move to"
    print(f"\n[setup] using location '{target}' for move test")

    chaos.set_binding(BUTTON_ID, "single", "move_to_location", {"location": target})
    yield target

    chaos.clear_binding(BUTTON_ID)
    orig_single = (original or {}).get("bindings", {}).get("single")
    if orig_single:
        chaos.set_binding(BUTTON_ID, "single",
                          orig_single["action"],
                          orig_single.get("params", {}))


def test_disconnect_during_command_clears_executing(chaos, with_move_binding):
    target = with_move_binding

    # Baseline
    assert chaos.wait_robot_online(timeout=15)
    chaos.cancel_queue()
    time.sleep(2)

    # 1. Fire the move command
    print(f"\n[step 1] firing move_to_location -> {target}")
    chaos.fire_button(BUTTON_IEEE, "single")

    # 2. Wait until executing
    started = False
    for _ in range(15):
        time.sleep(1)
        q = chaos.get_queue()
        items = q.get("items", [])
        if any(i.get("status") == "executing" for i in items) or items:
            started = True
            print(f"[step 2] queue has executing item: {items}")
            break

    # If queue didn't show executing, the action may have gone through direct path.
    # Either way, give the robot 5s to start moving.
    time.sleep(5)
    print(f"[step 2] after 5s queue: {chaos.get_queue()}")

    # 3. Disconnect mid-command
    disrupt_at = time.time()
    print(f"\n[step 3] PATCH robot IP -> {BOGUS_IP}")
    chaos.patch_robot_ip(BOGUS_IP)

    # 4. Watch how long _executing stays populated
    cleared_after = None
    for sec in range(150):  # 150s window — SDK timeout is 120s
        time.sleep(1)
        q = chaos.get_queue()
        items = q.get("items", [])
        executing = [i for i in items if i.get("status") == "executing"]
        if not executing and not items:
            cleared_after = time.time() - disrupt_at
            print(f"[step 4] queue cleared after {cleared_after:.1f}s")
            break
        if sec % 10 == 0:
            print(f"  t+{sec}s: queue={items}")

    # Cleanup happens in safety_finalizer
    print(f"\n[result] _executing cleared after disconnect: {cleared_after}s")

    assert cleared_after is not None, (
        "BUG: queue _executing slot never cleared in 150s window. "
        "Backend has no disconnect detection mid-command (CORNER-004)."
    )
    assert cleared_after < 30, (
        f"BUG: _executing only cleared after {cleared_after:.1f}s — "
        f"likely waiting for full SDK timeout (~120s). Backend should detect "
        f"disconnect faster (CORNER-004)."
    )
