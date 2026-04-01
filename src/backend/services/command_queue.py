from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    import aiosqlite
    from services.action_executor import ActionExecutor
    from services.robot_manager import RobotManager
    from services.ws_manager import WSManager

logger = get_logger("command_queue")


@dataclass
class QueueItem:
    id: str
    robot_id: str
    action: str
    params: dict
    status: str = "pending"
    button_id: int | None = None
    trigger: str | None = None
    enqueued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class CommandQueue:
    def __init__(
        self,
        action_executor: ActionExecutor,
        robot_manager: RobotManager,
        ws_manager: WSManager,
        db: aiosqlite.Connection,
    ):
        self._executor = action_executor
        self._robot_manager = robot_manager
        self._ws = ws_manager
        self._db = db
        self._queues: dict[str, list[QueueItem]] = {}
        self._executing: dict[str, QueueItem | None] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._enabled: bool = True

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        logger.info(f"Command queue {'enabled' if enabled else 'disabled'}")

    def get_all(self) -> list[dict]:
        items = []
        for robot_id, executing in self._executing.items():
            if executing:
                items.append(executing.to_dict())
        for robot_id, queue in self._queues.items():
            for item in queue:
                items.append(item.to_dict())
        return items

    async def enqueue(
        self,
        robot_id: str,
        action: str,
        params: dict,
        button_id: int | None = None,
        trigger: str | None = None,
    ) -> dict:
        if not self._enabled:
            return await self._execute_direct(robot_id, action, params, button_id, trigger)

        robot_queue = self._queues.get(robot_id, [])
        if robot_queue:
            last = robot_queue[-1]
            if last.action == action and last.params == params:
                logger.info(f"Debounced {action} on {robot_id}")
                return {"ok": False, "error": "Debounced: duplicate of last queued command"}

        item = QueueItem(
            id=str(uuid.uuid4()),
            robot_id=robot_id,
            action=action,
            params=params,
            button_id=button_id,
            trigger=trigger,
        )
        if robot_id not in self._queues:
            self._queues[robot_id] = []
        self._queues[robot_id].append(item)
        position = len(self._queues[robot_id])

        logger.info(f"Enqueued {action} on {robot_id}, position={position}")
        await self._ws.broadcast("queue:added", {
            "id": item.id,
            "robot_id": robot_id,
            "action": action,
            "params": params,
            "position": position,
        })

        if robot_id not in self._workers or self._workers[robot_id].done():
            self._workers[robot_id] = asyncio.create_task(self._worker(robot_id))

        return {"ok": True, "queue_id": item.id, "position": position}

    async def _execute_direct(
        self,
        robot_id: str,
        action: str,
        params: dict,
        button_id: int | None,
        trigger: str | None,
    ) -> dict:
        """Execute directly when queue is disabled."""
        if self._executing.get(robot_id):
            logger.info(f"Rejected {action} on {robot_id}: busy (queue disabled)")
            await self._ws.broadcast("queue:rejected", {
                "robot_id": robot_id,
                "action": action,
                "error": "Robot busy, queue disabled",
            })
            return {"ok": False, "error": "Robot busy, queue disabled"}

        item = QueueItem(
            id=str(uuid.uuid4()),
            robot_id=robot_id,
            action=action,
            params=params,
            button_id=button_id,
            trigger=trigger,
            status="executing",
        )
        self._executing[robot_id] = item

        try:
            result = await self._executor.execute(robot_id, action, params)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
            logger.error(f"Direct execution error for {action} on {robot_id}: {e}")

        self._executing[robot_id] = None
        await self._write_action_log(item, result)
        await self._ws.broadcast("action_executed", {
            "button_id": button_id,
            "trigger": trigger,
            "robot_id": robot_id,
            "action": action,
            "result": result,
        })
        return result

    async def _worker(self, robot_id: str) -> None:
        """Process queue items sequentially for a robot."""
        logger.info(f"Worker started for {robot_id}")
        try:
            while self._queues.get(robot_id):
                item = self._queues[robot_id].pop(0)
                item.status = "executing"
                self._executing[robot_id] = item

                await self._ws.broadcast("queue:executing", {
                    "id": item.id,
                    "robot_id": robot_id,
                    "action": item.action,
                    "params": item.params,
                })

                try:
                    result = await self._executor.execute(robot_id, item.action, item.params)
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                    logger.error(f"Worker error executing {item.action} on {robot_id}: {e}")

                self._executing[robot_id] = None
                await self._write_action_log(item, result)

                await self._ws.broadcast("queue:completed", {
                    "id": item.id,
                    "robot_id": robot_id,
                    "action": item.action,
                    "result": result,
                })
                await self._ws.broadcast("action_executed", {
                    "button_id": item.button_id,
                    "trigger": item.trigger,
                    "robot_id": robot_id,
                    "action": item.action,
                    "result": result,
                })
        finally:
            self._workers.pop(robot_id, None)
            logger.info(f"Worker stopped for {robot_id}")

    async def remove(self, queue_id: str) -> dict:
        """Remove a pending item from the queue."""
        for robot_id, queue in self._queues.items():
            for i, item in enumerate(queue):
                if item.id == queue_id:
                    queue.pop(i)
                    logger.info(f"Removed {item.action} from {robot_id} queue")
                    await self._ws.broadcast("queue:removed", {
                        "id": queue_id,
                        "robot_id": robot_id,
                    })
                    return {"ok": True}
        return {"ok": False, "error": "Item not found in queue"}

    async def cancel_current(self, robot_id: str) -> dict:
        """Cancel the currently executing command on a robot."""
        executing = self._executing.get(robot_id)
        if not executing:
            return {"ok": True, "message": "no command running"}

        svc = self._robot_manager.get(robot_id)
        if not svc or not svc.commands:
            return {"ok": False, "error": f"Robot '{robot_id}' not connected"}

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, svc.commands.cancel_command)
            logger.info(f"Cancelled command on {robot_id}")
            await self._ws.broadcast("queue:cancelled", {
                "id": executing.id,
                "robot_id": robot_id,
            })
            return {"ok": True}
        except Exception as e:
            logger.error(f"Failed to cancel on {robot_id}: {e}")
            return {"ok": False, "error": str(e)}

    async def _write_action_log(self, item: QueueItem, result: dict) -> None:
        """Write execution result to action_logs table."""
        now = datetime.now(timezone.utc).isoformat()
        params_json = json.dumps(item.params) if item.params else "{}"
        try:
            await self._db.execute(
                "INSERT INTO action_logs (button_id, trigger, robot_id, action, params, "
                "result_ok, result_detail, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.button_id,
                    item.trigger,
                    item.robot_id,
                    item.action,
                    params_json,
                    1 if result.get("ok") else 0,
                    json.dumps(result),
                    now,
                ),
            )
            await self._db.commit()
        except Exception as e:
            logger.error(f"Failed to write action log: {e}")
