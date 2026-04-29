from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite
    from services.route_service import RouteService
    from services.robot_manager import RobotManager
    from services.ws_manager import WSManager

logger = get_logger("route_dispatcher")


class RouteDispatcher:
    def __init__(
        self,
        db: aiosqlite.Connection,
        ws_manager: WSManager,
        robot_manager: RobotManager,
    ):
        self._db = db
        self._ws = ws_manager
        self._rm = robot_manager
        self._route_service: RouteService | None = None
        self._last_assigned: str | None = None
        self._queue: list[str] = []
        self._active: dict[str, str] = {}
        self._generator = None
        self._deployer = None
        self._route_mode = "online"
        self._pi_url = ""

    def set_route_service(self, svc: RouteService) -> None:
        self._route_service = svc

    def set_offline_components(self, generator, deployer) -> None:
        self._generator = generator
        self._deployer = deployer

    def set_route_mode(self, mode: str) -> None:
        self._route_mode = mode

    def set_pi_url(self, url: str) -> None:
        self._pi_url = url

    async def dispatch(
        self,
        stops: list[dict] | None = None,
        default_timeout: int = 120,
        confirm_button_id: int | None = None,
        pinned_robot_id: str | None = None,
        template_id: str | None = None,
        shelf_name: str | None = None,
    ) -> dict:
        if template_id and not stops:
            async with self._db.execute(
                "SELECT stops, default_timeout, confirm_button_id, pinned_robot_id, shelf_name "
                "FROM route_templates WHERE id = ?",
                (template_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return {"ok": False, "error": f"Template '{template_id}' not found"}
            stops = json.loads(row[0])
            default_timeout = row[1]
            confirm_button_id = row[2]
            pinned_robot_id = row[3]
            shelf_name = row[4] if not shelf_name else shelf_name

        if not stops:
            return {"ok": False, "error": "No stops provided"}

        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        robot_id = self._pick_robot(pinned_robot_id)
        status = "assigned" if robot_id else "queued"

        await self._db.execute(
            "INSERT INTO route_runs (id, template_id, robot_id, stops, default_timeout, "
            "confirm_button_id, shelf_name, status, current_stop, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, -1, ?)",
            (run_id, template_id, robot_id, json.dumps(stops), default_timeout,
             confirm_button_id, shelf_name, status, now if robot_id else None),
        )
        await self._db.commit()

        if robot_id and self._route_mode == "offline" and self._generator and self._deployer:
            # Offline path: generate script and deploy via SSH
            self._active[robot_id] = run_id
            self._last_assigned = robot_id
            robot_svc = self._rm.get(robot_id)
            robot_ip = getattr(robot_svc, 'ip', None) or robot_id

            script = self._generator.generate(
                run_id=run_id,
                stops=stops,
                shelf_name=shelf_name or "",
                default_timeout=default_timeout,
                pi_url=self._pi_url,
            )

            deploy_result = await self._deployer.deploy(robot_ip, script, run_id)
            if deploy_result.get("ok"):
                await self._db.execute(
                    "UPDATE route_runs SET status = 'offline_running', execution_mode = 'offline' WHERE id = ?",
                    (run_id,),
                )
                await self._db.commit()
                await self._ws.broadcast("route:offline_started", {"run_id": run_id, "robot_id": robot_id})
                return {"ok": True, "run_id": run_id, "robot_id": robot_id, "status": "offline_running"}
            else:
                self._active.pop(robot_id, None)
                await self._db.execute(
                    "UPDATE route_runs SET status = 'failed', completed_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), run_id),
                )
                await self._db.commit()
                return {"ok": False, "error": deploy_result.get("error", "Deploy failed")}

        elif robot_id:
            self._active[robot_id] = run_id
            self._last_assigned = robot_id
            logger.info(f"Route {run_id} assigned to {robot_id}")
            await self._ws.broadcast("route:assigned", {"run_id": run_id, "robot_id": robot_id})
            if self._route_service:
                await self._route_service.start_run(run_id, robot_id)
        else:
            self._queue.append(run_id)
            logger.info(f"Route {run_id} queued (all robots busy)")
            await self._ws.broadcast("route:queued", {"run_id": run_id, "stops": stops})

        return {"ok": True, "run_id": run_id, "robot_id": robot_id, "status": status}

    def _pick_robot(self, pinned_robot_id: str | None) -> str | None:
        robot_ids = self._rm.all_ids()
        if not robot_ids:
            return None
        if pinned_robot_id:
            if pinned_robot_id not in self._active:
                return pinned_robot_id
            return None
        if self._last_assigned and self._last_assigned in robot_ids:
            idx = robot_ids.index(self._last_assigned)
            order = robot_ids[idx + 1:] + robot_ids[:idx + 1]
        else:
            order = robot_ids
        for rid in order:
            if rid not in self._active:
                return rid
        return None

    async def on_route_done(self, run_id: str, robot_id: str) -> None:
        self._active.pop(robot_id, None)
        logger.info(f"Route {run_id} done on {robot_id}, checking queue")
        if not self._queue:
            return
        next_run_id = self._queue.pop(0)
        async with self._db.execute(
            "SELECT stops, default_timeout, confirm_button_id "
            "FROM route_runs WHERE id = ? AND status = 'queued'",
            (next_run_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return
        self._active[robot_id] = next_run_id
        self._last_assigned = robot_id
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE route_runs SET robot_id = ?, status = 'assigned', started_at = ? WHERE id = ?",
            (robot_id, now, next_run_id),
        )
        await self._db.commit()
        logger.info(f"Dequeued route {next_run_id} -> {robot_id}")
        await self._ws.broadcast("route:assigned", {"run_id": next_run_id, "robot_id": robot_id})
        if self._route_service:
            await self._route_service.start_run(next_run_id, robot_id)

    async def cancel(self, run_id: str) -> dict:
        if run_id in self._queue:
            self._queue.remove(run_id)
            await self._db.execute(
                "UPDATE route_runs SET status = 'cancelled', completed_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), run_id),
            )
            await self._db.commit()
            await self._ws.broadcast("route:cancelled", {"run_id": run_id})
            return {"ok": True}
        for robot_id, active_run_id in self._active.items():
            if active_run_id == run_id:
                # Check if offline run — cancel directly in DB
                async with self._db.execute(
                    "SELECT execution_mode FROM route_runs WHERE id = ?", (run_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row and row[0] == "offline":
                    self._active.pop(robot_id, None)
                    await self._db.execute(
                        "UPDATE route_runs SET status = 'cancelled', completed_at = ? WHERE id = ?",
                        (datetime.now(timezone.utc).isoformat(), run_id),
                    )
                    await self._db.commit()
                    await self._ws.broadcast("route:cancelled", {"run_id": run_id})
                elif self._route_service:
                    await self._route_service.cancel_run(run_id)
                return {"ok": True}
        return {"ok": False, "error": "Run not found"}

    def get_status(self) -> dict:
        return {
            "last_assigned": self._last_assigned,
            "queue_length": len(self._queue),
            "queue": list(self._queue),
            "active": dict(self._active),
        }

    async def rebuild_from_db(self) -> None:
        # Mark stale offline_running as completed (no way to resume after restart)
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            "UPDATE route_runs SET status = 'completed', completed_at = ? "
            "WHERE status = 'offline_running'", (now,),
        )
        if cursor.rowcount:
            logger.info(f"Cleaned {cursor.rowcount} stale offline_running runs")
            await self._db.commit()

        async with self._db.execute(
            "SELECT id FROM route_runs WHERE status = 'queued' ORDER BY started_at"
        ) as cursor:
            rows = await cursor.fetchall()
        self._queue = [row[0] for row in rows]
        async with self._db.execute(
            "SELECT id, robot_id FROM route_runs WHERE status IN ('assigned', 'running')"
        ) as cursor:
            rows = await cursor.fetchall()
        for run_id, robot_id in rows:
            if robot_id:
                self._active[robot_id] = run_id
        logger.info(f"Rebuilt dispatcher: {len(self._queue)} queued, {len(self._active)} active")
