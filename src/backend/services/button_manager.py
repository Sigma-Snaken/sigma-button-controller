from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiosqlite

from services.ws_manager import WSManager
from utils.logger import get_logger

if TYPE_CHECKING:
    from services.command_queue import CommandQueue

logger = get_logger("button_manager")


class ButtonManager:
    def __init__(
        self,
        db: aiosqlite.Connection,
        command_queue: CommandQueue,
        ws_manager: WSManager,
    ):
        self._db = db
        self._queue = command_queue
        self._ws = ws_manager
        self._route_service = None
        self._route_dispatcher = None

    def set_route_service(self, route_service) -> None:
        self._route_service = route_service

    def set_route_dispatcher(self, route_dispatcher) -> None:
        self._route_dispatcher = route_dispatcher

    async def handle_message(self, msg: dict) -> None:
        msg_type = msg.get("type")
        if msg_type == "device_joined":
            await self._on_device_joined(msg)
        elif msg_type == "device_announce":
            await self._on_device_announce(msg)
        elif msg_type == "button_action":
            await self._on_button_action(msg)

    async def _on_device_joined(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        async with self._db.execute(
            "SELECT id FROM buttons WHERE ieee_addr = ?", (ieee,)
        ) as cursor:
            if await cursor.fetchone():
                logger.info(f"Device {ieee} already paired, skipping")
                return

        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO buttons (ieee_addr, name, paired_at) VALUES (?, ?, ?)",
            (ieee, ieee, now),
        )
        await self._db.commit()
        logger.info(f"New device paired: {ieee}")

        async with self._db.execute(
            "SELECT id, ieee_addr, name, paired_at FROM buttons WHERE ieee_addr = ?",
            (ieee,),
        ) as cursor:
            row = await cursor.fetchone()

        await self._ws.broadcast("device_paired", {
            "id": row[0],
            "ieee_addr": row[1],
            "name": row[2],
            "paired_at": row[3],
        })

    async def _on_device_announce(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE buttons SET last_seen = ? WHERE ieee_addr = ?", (now, ieee)
        )
        await self._db.commit()

    async def _on_button_action(self, msg: dict) -> None:
        ieee = msg["ieee_addr"]
        trigger = msg["action"]
        now = datetime.now(timezone.utc).isoformat()

        # Update battery + last_seen
        if msg.get("battery") is not None:
            await self._db.execute(
                "UPDATE buttons SET battery = ?, last_seen = ? WHERE ieee_addr = ?",
                (msg["battery"], now, ieee),
            )
        else:
            await self._db.execute(
                "UPDATE buttons SET last_seen = ? WHERE ieee_addr = ?", (now, ieee),
            )
        await self._db.commit()

        # Broadcast button activity so frontend refreshes last_seen
        await self._ws.broadcast("button:activity", {
            "ieee_addr": ieee,
            "trigger": trigger,
            "battery": msg.get("battery"),
            "last_seen": now,
        })

        # Route confirmation interception
        if self._route_service and self._route_service.try_confirm(ieee):
            logger.info(f"Button {ieee} confirmed route stop")
            return

        async with self._db.execute(
            "SELECT id FROM buttons WHERE ieee_addr = ?", (ieee,)
        ) as cursor:
            button_row = await cursor.fetchone()
        if not button_row:
            logger.warning(f"Unknown button: {ieee}")
            return

        button_id = button_row[0]

        async with self._db.execute(
            "SELECT robot_id, action, params FROM bindings "
            "WHERE button_id = ? AND trigger = ? AND enabled = 1",
            (button_id, trigger),
        ) as cursor:
            binding = await cursor.fetchone()

        if not binding:
            logger.info(f"No binding for button {ieee} trigger={trigger}")
            return

        robot_id, action, params_json = binding
        params = json.loads(params_json) if params_json else {}

        logger.info(f"Button {ieee} trigger={trigger} -> {action} on {robot_id}")

        if action == "cancel_command":
            result = await self._queue.cancel_current(robot_id)
            # Log cancel action directly
            now = datetime.now(timezone.utc).isoformat()
            await self._db.execute(
                "INSERT INTO action_logs (button_id, trigger, robot_id, action, params, "
                "result_ok, result_detail, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (button_id, trigger, robot_id, action, params_json,
                 1 if result.get("ok") else 0, json.dumps(result), now),
            )
            await self._db.commit()
            await self._ws.broadcast("action_executed", {
                "button_id": button_id,
                "trigger": trigger,
                "robot_id": robot_id,
                "action": action,
                "result": result,
            })
        elif action == "start_route":
            if self._route_dispatcher:
                result = await self._route_dispatcher.dispatch(
                    template_id=params.get("template_id"),
                )
                now = datetime.now(timezone.utc).isoformat()
                await self._db.execute(
                    "INSERT INTO action_logs (button_id, trigger, robot_id, action, params, "
                    "result_ok, result_detail, executed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (button_id, trigger, robot_id, action, params_json,
                     1 if result.get("ok") else 0, json.dumps(result), now),
                )
                await self._db.commit()
                await self._ws.broadcast("action_executed", {
                    "button_id": button_id, "trigger": trigger,
                    "robot_id": robot_id, "action": action, "result": result,
                })
            else:
                logger.warning("start_route action but no route dispatcher")
        else:
            await self._queue.enqueue(
                robot_id, action, params,
                button_id=button_id, trigger=trigger,
            )
