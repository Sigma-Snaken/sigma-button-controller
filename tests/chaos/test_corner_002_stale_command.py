"""
CORNER-002: stale commands fire after robot reconnect.

Scenario:
  Robot is unreachable. User mashes the button N times.
  When the robot comes back, the queued commands all dispatch in order
  — even if those button presses are minutes-old and stale.

Pass criteria:
  - The 3 stale move commands should NOT all execute back-to-back after reconnect.
  - At least one of: (a) backend rejects new presses while robot disconnected,
    (b) queue items get dropped/marked stale on reconnect, (c) WS warns user.

Likely outcome: this test will FAIL — the queue likely happily fires
all 3 moves once IP is restored.

Verification: monitor `_executing` + queue length transitions, plus the
final action_logs to see how many `move_to_location` calls were dispatched.
"""
import time

import pytest

from .conftest import BOGUS_IP


pytestmark = [pytest.mark.chaos, pytest.mark.batch1]

BUTTON_IEEE = "0x08ddebfffea3a363"  # button id 5, name "111"
BUTTON_ID = 5


@pytest.fixture
def with_test_binding(chaos):
    """Set up: button 5 single → return_home (safe + observable)."""
    # Save existing binding
    original = chaos.get_binding(BUTTON_ID)
    chaos.set_binding(BUTTON_ID, "single", "return_home")
    yield
    # Restore: clear, then re-apply original singles if any
    chaos.clear_binding(BUTTON_ID)
    orig_single = (original or {}).get("bindings", {}).get("single")
    if orig_single:
        body_payload = {
            "single": {
                "robot_id": orig_single["robot_id"],
                "action": orig_single["action"],
                "params": orig_single.get("params", {}),
            }
        }
        # Use raw set_binding helper would conflict — re-use http directly via the helper
        chaos.set_binding(BUTTON_ID, "single",
                          orig_single["action"],
                          orig_single.get("params", {}))


def _count_action_logs_since(chaos, since_iso, action_name):
    import httpx
    with httpx.Client(timeout=10) as c:
        r = c.get(f"{chaos.base_url}/api/logs?per_page=100", timeout=10).json()
    items = r.get("logs", [])
    return sum(
        1 for item in items
        if item.get("action") == action_name
        and item.get("executed_at", "") >= since_iso
    )


def test_stale_commands_after_reconnect(chaos, with_test_binding):
    from datetime import datetime, timezone

    # Baseline: robot online, queue empty
    assert chaos.wait_robot_online(timeout=15), "Robot must be online before test"
    chaos.cancel_queue()
    test_start = datetime.now(timezone.utc).isoformat()

    # 1. Disconnect robot via API (PATCH IP to bogus)
    print(f"\n[step 1] PATCH robot IP -> {BOGUS_IP}")
    chaos.patch_robot_ip(BOGUS_IP)
    time.sleep(5)  # let reconnect attempt fail

    robot = chaos.get_robot()
    print(f"[step 1] robot state: online={robot.get('online')} "
          f"conn={robot.get('connection_state')} ip={robot.get('ip')}")

    # 2. Fire 3 button presses (queued or rejected — let's see)
    print(f"\n[step 2] firing 3 button presses while disconnected")
    for i in range(3):
        rc, out, err = chaos.fire_button(BUTTON_IEEE, "single")
        print(f"  press {i+1}: rc={rc} err={err[:80] if err else ''}")
        time.sleep(2)

    queue_during = chaos.get_queue()
    print(f"[step 2] queue while disconnected: {len(queue_during.get('items', []))} item(s)")

    # 3. Restore IP, watch what happens
    print(f"\n[step 3] PATCH robot IP -> {chaos.robot_ip} (restore)")
    chaos.restore_robot_ip()

    # Watch queue + action_logs over next 30s
    move_dispatched = 0
    for sec in range(30):
        time.sleep(1)
        q = chaos.get_queue()
        n = _count_action_logs_since(chaos, test_start, "return_home")
        if n > move_dispatched:
            move_dispatched = n
            print(f"  t+{sec+1}s: queue={len(q.get('items', []))} "
                  f"return_home_logs={n}")

    print(f"\n[step 3] final return_home dispatches since test start: {move_dispatched}")
    print(f"[step 3] final queue: {chaos.get_queue()}")

    # Pass = "stale storm" was prevented. Likely FAIL — that IS the bug.
    # We allow up to 1 (the most recent is acceptable; the older 2 are stale).
    assert move_dispatched <= 1, (
        f"BUG: {move_dispatched} stale return_home commands fired after reconnect "
        f"(expected ≤1). Stale commands from before disconnect should not dispatch. "
        f"This is CORNER-002."
    )
