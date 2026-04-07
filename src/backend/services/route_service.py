from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite
    from services.route_dispatcher import RouteDispatcher

logger = get_logger("route_service")


@dataclass
class _RunState:
    run_id: str
    robot_id: str
    stops: list[dict]
    default_timeout: int
    confirm_button_id: int | None
    current_stop: int = -1
    cancelled: bool = False
    waiting_event: asyncio.Event = field(default_factory=asyncio.Event)
    _confirm_ieee: str | None = None


class RouteService:
    def __init__(
        self,
        db: aiosqlite.Connection,
        action_executor,
        ws_manager,
        notifier,
    ):
        self._db = db
        self._executor = action_executor
        self._ws = ws_manager
        self._notifier = notifier
        self._dispatcher: RouteDispatcher | None = None
        self._runs: dict[str, _RunState] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def set_dispatcher(self, dispatcher: RouteDispatcher) -> None:
        self._dispatcher = dispatcher

    async def start_run(self, run_id: str, robot_id: str) -> None:
        async with self._db.execute(
            "SELECT stops, default_timeout, confirm_button_id FROM route_runs WHERE id = ?",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            logger.error(f"Route run {run_id} not found in DB")
            return

        stops = json.loads(row[0])
        default_timeout = row[1]
        confirm_button_id = row[2]

        state = _RunState(
            run_id=run_id,
            robot_id=robot_id,
            stops=stops,
            default_timeout=default_timeout,
            confirm_button_id=confirm_button_id,
        )
        self._runs[run_id] = state
        task = asyncio.create_task(self._execute_route(state))
        self._tasks[run_id] = task
        logger.info(f"Started route {run_id} on {robot_id} ({len(stops)} stops)")

    async def cancel_run(self, run_id: str) -> None:
        state = self._runs.get(run_id)
        if not state:
            return
        state.cancelled = True
        state.waiting_event.set()
        logger.info(f"Cancelling route {run_id}")

    def try_confirm(self, ieee_addr: str) -> bool:
        for state in self._runs.values():
            if state.current_stop >= 0 and not state.cancelled:
                # Check if this run is actively waiting (event not yet set)
                if not state.waiting_event.is_set():
                    state._confirm_ieee = ieee_addr
                    state.waiting_event.set()
                    logger.info(f"Button {ieee_addr} confirmed run {state.run_id} at stop {state.current_stop}")
                    return True
        return False

    def get_active_runs(self) -> dict:
        result = {}
        for run_id, state in self._runs.items():
            result[run_id] = {
                "robot_id": state.robot_id,
                "current_stop": state.current_stop,
                "total_stops": len(state.stops),
                "cancelled": state.cancelled,
            }
        return result

    async def _execute_route(self, state: _RunState) -> None:
        run_id = state.run_id
        robot_id = state.robot_id

        try:
            await self._update_run_status(run_id, "running")
            await self._ws.broadcast("route:running", {
                "run_id": run_id, "robot_id": robot_id,
            })

            for i, stop in enumerate(state.stops):
                if state.cancelled:
                    break

                state.current_stop = i
                location = stop["name"]
                await self._db.execute(
                    "UPDATE route_runs SET current_stop = ? WHERE id = ?",
                    (i, run_id),
                )
                await self._db.commit()

                await self._ws.broadcast("route:moving", {
                    "run_id": run_id, "robot_id": robot_id,
                    "stop_index": i, "location": location,
                })

                # Move to location
                result = await self._executor.execute(
                    robot_id, "move_to_location", {"name": location},
                )
                if not result.get("ok") and not state.cancelled:
                    logger.error(f"Move to {location} failed: {result}")

                if state.cancelled:
                    break

                arrived_at = datetime.now(timezone.utc).isoformat()

                # Determine timeout for this stop
                timeout = stop.get("timeout_sec", state.default_timeout)

                # Determine if we should wait for button confirm
                use_confirm = self._resolve_confirm_button(state, stop)

                if use_confirm:
                    confirmed, ieee = await self._wait_at_stop(state, timeout)
                else:
                    confirmed = False
                    ieee = None
                    await self._countdown(state, timeout)

                departed_at = datetime.now(timezone.utc).isoformat()
                timed_out = not confirmed and not state.cancelled

                if timed_out and not state.cancelled:
                    await self._notify_timeout(state, i, location)

                await self._write_stop_log(
                    run_id=run_id,
                    stop_index=i,
                    location_name=location,
                    arrived_at=arrived_at,
                    confirmed_at=departed_at if confirmed else None,
                    confirmed_by=ieee,
                    timed_out=timed_out and not state.cancelled,
                    departed_at=departed_at,
                )

                if state.cancelled:
                    break

            # Finishing: return shelf + return home
            await self._executor.execute(robot_id, "return_shelf", {})
            await self._executor.execute(robot_id, "return_home", {})

            # Set final status
            if state.cancelled:
                final_status = "cancelled"
            else:
                final_status = "completed"

            await self._update_run_status(run_id, final_status)
            await self._ws.broadcast(f"route:{final_status}", {
                "run_id": run_id, "robot_id": robot_id,
            })

        except asyncio.CancelledError:
            await self._update_run_status(run_id, "cancelled")
            raise
        except Exception as e:
            logger.error(f"Route {run_id} failed: {e}", exc_info=True)
            await self._update_run_status(run_id, "failed")
            await self._ws.broadcast("route:failed", {
                "run_id": run_id, "robot_id": robot_id, "error": str(e),
            })
        finally:
            self._runs.pop(run_id, None)
            self._tasks.pop(run_id, None)
            if self._dispatcher:
                await self._dispatcher.on_route_done(run_id, robot_id)

    def _resolve_confirm_button(self, state: _RunState, stop: dict) -> bool:
        """Check if this stop should wait for button confirmation."""
        # Per-stop override
        if "confirm_button_id" in stop:
            return stop["confirm_button_id"] is not None
        # Route-level setting
        return state.confirm_button_id is not None

    async def _wait_at_stop(self, state: _RunState, timeout: int) -> tuple[bool, str | None]:
        """Wait at a stop for button confirmation or timeout, broadcasting countdown."""
        state.waiting_event.clear()
        state._confirm_ieee = None
        remaining = timeout

        while remaining > 0 and not state.cancelled:
            await self._ws.broadcast("route:waiting", {
                "run_id": state.run_id,
                "robot_id": state.robot_id,
                "stop_index": state.current_stop,
                "remaining": remaining,
            })
            try:
                await asyncio.wait_for(state.waiting_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                remaining -= 1
                continue

            # Event was set
            if state.cancelled:
                return False, None
            if state._confirm_ieee:
                return True, state._confirm_ieee
            # Spurious wake — reset and continue
            state.waiting_event.clear()

        return False, None

    async def _countdown(self, state: _RunState, timeout: int) -> None:
        """Simple countdown when no confirm button is set."""
        remaining = timeout
        while remaining > 0 and not state.cancelled:
            await self._ws.broadcast("route:waiting", {
                "run_id": state.run_id,
                "robot_id": state.robot_id,
                "stop_index": state.current_stop,
                "remaining": remaining,
            })
            try:
                await asyncio.wait_for(state.waiting_event.wait(), timeout=1.0)
                if state.cancelled:
                    return
            except asyncio.TimeoutError:
                pass
            remaining -= 1

    async def _notify_timeout(self, state: _RunState, stop_index: int, location: str) -> None:
        """Send notification that a stop timed out without confirmation."""
        message = (
            f"Route {state.run_id[:8]}... timed out at stop {stop_index + 1} ({location}). "
            f"Robot: {state.robot_id}. Proceeding to next stop."
        )
        try:
            await self._notifier.send(message)
        except Exception as e:
            logger.error(f"Failed to send timeout notification: {e}")

    async def _write_stop_log(
        self,
        run_id: str,
        stop_index: int,
        location_name: str,
        arrived_at: str,
        confirmed_at: str | None,
        confirmed_by: str | None,
        timed_out: bool,
        departed_at: str,
    ) -> None:
        await self._db.execute(
            "INSERT INTO route_stop_logs "
            "(run_id, stop_index, location_name, arrived_at, confirmed_at, confirmed_by, timed_out, departed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, stop_index, location_name, arrived_at, confirmed_at, confirmed_by, timed_out, departed_at),
        )
        await self._db.commit()

    async def _update_run_status(self, run_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if status in ("completed", "cancelled", "failed"):
            await self._db.execute(
                "UPDATE route_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status, now, run_id),
            )
        else:
            await self._db.execute(
                "UPDATE route_runs SET status = ? WHERE id = ?",
                (status, run_id),
            )
        await self._db.commit()
