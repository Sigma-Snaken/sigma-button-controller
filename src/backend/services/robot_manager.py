from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from kachaka_core.connection import KachakaConnection, ConnectionState
from kachaka_core.commands import KachakaCommands
from kachaka_core.queries import KachakaQueries
from kachaka_core.camera import CameraStreamer
from kachaka_core.controller import RobotController

from utils.logger import get_logger

if TYPE_CHECKING:
    from services.ws_manager import WSManager

logger = get_logger("robot_manager")


class RobotService:
    """Wraps kachaka_core components for a single robot."""

    def __init__(self, robot_id: str, ip: str, *, ws_manager: WSManager | None = None, loop: asyncio.AbstractEventLoop | None = None):
        self.robot_id = robot_id
        self.ip = ip
        self.conn = None
        self.commands: KachakaCommands | None = None
        self.queries: KachakaQueries | None = None
        self.controller: RobotController | None = None
        self.front_streamer: CameraStreamer | None = None
        self.back_streamer: CameraStreamer | None = None
        self._ws_manager = ws_manager
        self._loop = loop

    def connect(self, connect_fn=None, commands_cls=None, queries_cls=None) -> dict:
        _connect = connect_fn or KachakaConnection.get
        _cmds_cls = commands_cls or KachakaCommands
        _queries_cls = queries_cls or KachakaQueries
        self.conn = _connect(self.ip)
        self.commands = _cmds_cls(self.conn)
        self.queries = _queries_cls(self.conn)
        result = self.conn.ping()
        logger.info(f"Connected to robot {self.robot_id} at {self.ip}: {self.conn.serial or 'unknown'}")

        # Start connection monitoring BEFORE controller.start().
        # RobotController.start() also calls conn.start_monitoring() internally,
        # but since it's idempotent (no-op if thread is alive), our callback wins.
        # _on_state_change manually delegates to controller._on_conn_state_change
        # so all subsystems still receive state updates.
        try:
            self.conn.start_monitoring(
                interval=5.0,
                on_state_change=self._on_state_change,
            )
            logger.info(f"Connection monitoring started for {self.robot_id}")
        except Exception as e:
            logger.warning(f"Could not start monitoring for {self.robot_id}: {e}")

        # Initialize RobotController for background polling + metrics
        try:
            self.controller = RobotController(
                self.conn,
                on_shelf_dropped=self._on_shelf_dropped,
            )
            self.controller.start()
            logger.info(f"RobotController started for {self.robot_id}")
        except Exception as e:
            logger.warning(f"Could not init RobotController for {self.robot_id}: {e}")

        return result

    # ------------------------------------------------------------------
    # Callbacks (called from background threads)
    # ------------------------------------------------------------------

    def _on_state_change(self, state: ConnectionState) -> None:
        """Fan out connection state changes to all subsystems."""
        logger.info(f"Robot {self.robot_id} connection state -> {state.value}")

        # 1. Notify controller (updates RobotState fields)
        if self.controller:
            try:
                self.controller._on_conn_state_change(state)
            except Exception as e:
                logger.warning(f"Controller state change error: {e}")

        # 2. Notify active camera streamers
        for streamer in (self.front_streamer, self.back_streamer):
            if streamer:
                try:
                    streamer.notify_state_change(state)
                except Exception as e:
                    logger.warning(f"Streamer state change error: {e}")

        # 3. Invalidate Tier 2 caches on reconnect
        if state == ConnectionState.CONNECTED and self.conn:
            try:
                self.conn.refresh_shortcuts()
                self.conn.refresh_maps()
                logger.info(f"Tier 2 caches refreshed for {self.robot_id}")
            except Exception as e:
                logger.warning(f"Cache refresh error: {e}")

        # 4. Broadcast to WebSocket clients
        self._broadcast("robot:connection", {
            "robot_id": self.robot_id,
            "state": state.value,
        })

    def _on_shelf_dropped(self, shelf_id: str) -> None:
        """Broadcast shelf-drop event to WebSocket clients."""
        logger.info(f"Robot {self.robot_id} dropped shelf {shelf_id}")
        self._broadcast("robot:shelf_dropped", {
            "robot_id": self.robot_id,
            "shelf_id": shelf_id,
        })

    def _broadcast(self, event: str, data: dict) -> None:
        """Bridge thread callback to async WebSocket broadcast."""
        if not self._ws_manager or not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast(event, data),
                self._loop,
            )
        except Exception as e:
            logger.warning(f"WebSocket broadcast error: {e}")

    def start_streamer(self, camera: str) -> CameraStreamer | None:
        if camera == "front":
            if self.front_streamer and self.front_streamer.is_running:
                return self.front_streamer
            self.front_streamer = CameraStreamer(self.conn, interval=0.2, camera="front")
            self.front_streamer.start()
            logger.info(f"Front CameraStreamer started for {self.robot_id}")
            return self.front_streamer
        else:
            if self.back_streamer and self.back_streamer.is_running:
                return self.back_streamer
            self.back_streamer = CameraStreamer(self.conn, interval=0.2, camera="back")
            self.back_streamer.start()
            logger.info(f"Back CameraStreamer started for {self.robot_id}")
            return self.back_streamer

    def stop_streamer(self, camera: str) -> None:
        if camera == "front" and self.front_streamer:
            self.front_streamer.stop()
            self.front_streamer = None
            logger.info(f"Front CameraStreamer stopped for {self.robot_id}")
        elif camera == "back" and self.back_streamer:
            self.back_streamer.stop()
            self.back_streamer = None
            logger.info(f"Back CameraStreamer stopped for {self.robot_id}")

    def stop(self) -> None:
        if self.front_streamer:
            try: self.front_streamer.stop()
            except Exception: pass
            self.front_streamer = None
        if self.back_streamer:
            try: self.back_streamer.stop()
            except Exception: pass
            self.back_streamer = None
        if self.controller:
            try: self.controller.stop()
            except Exception: pass
        if self.conn:
            try: self.conn.stop_monitoring()
            except Exception: pass
            try: KachakaConnection.remove(self.ip)
            except Exception: pass
        logger.info(f"Stopped robot service for {self.robot_id}")


class RobotManager:
    """Manages multiple robot connections."""

    def __init__(self, *, ws_manager: WSManager | None = None, loop: asyncio.AbstractEventLoop | None = None):
        self._robots: dict[str, RobotService] = {}
        self._ws_manager = ws_manager
        self._loop = loop

    def add(self, robot_id: str, ip: str, **kwargs) -> RobotService:
        svc = RobotService(robot_id, ip, ws_manager=self._ws_manager, loop=self._loop)
        svc.connect(**kwargs)
        self._robots[robot_id] = svc
        return svc

    def remove(self, robot_id: str) -> None:
        svc = self._robots.pop(robot_id, None)
        if svc:
            svc.stop()

    def get(self, robot_id: str) -> RobotService | None:
        return self._robots.get(robot_id)

    def all_ids(self) -> list[str]:
        return list(self._robots.keys())

    def stop_all(self) -> None:
        for svc in self._robots.values():
            svc.stop()
        self._robots.clear()
