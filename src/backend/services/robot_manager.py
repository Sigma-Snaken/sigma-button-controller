from kachaka_core.connection import KachakaConnection
from kachaka_core.commands import KachakaCommands
from kachaka_core.queries import KachakaQueries
from kachaka_core.camera import CameraStreamer
from kachaka_core.controller import RobotController

from utils.logger import get_logger

logger = get_logger("robot_manager")


class RobotService:
    """Wraps kachaka_core components for a single robot."""

    def __init__(self, robot_id: str, ip: str):
        self.robot_id = robot_id
        self.ip = ip
        self.conn = None
        self.commands: KachakaCommands | None = None
        self.queries: KachakaQueries | None = None
        self.controller: RobotController | None = None
        self.serial: str | None = None
        self.front_streamer: CameraStreamer | None = None
        self.back_streamer: CameraStreamer | None = None

    def connect(self, connect_fn=None, commands_cls=None, queries_cls=None) -> dict:
        _connect = connect_fn or KachakaConnection.get
        _cmds_cls = commands_cls or KachakaCommands
        _queries_cls = queries_cls or KachakaQueries
        self.conn = _connect(self.ip)
        self.commands = _cmds_cls(self.conn)
        self.queries = _queries_cls(self.conn)
        result = self.conn.ping()
        self.serial = result.get('serial')
        logger.info(f"Connected to robot {self.robot_id} at {self.ip}: {self.serial or 'unknown'}")

        # Initialize RobotController for background polling + metrics
        try:
            self.controller = RobotController(self.conn)
            self.controller.start()
            logger.info(f"RobotController started for {self.robot_id}")
        except Exception as e:
            logger.warning(f"Could not init RobotController for {self.robot_id}: {e}")

        return result

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
        logger.info(f"Stopped robot service for {self.robot_id}")


class RobotManager:
    """Manages multiple robot connections."""

    def __init__(self):
        self._robots: dict[str, RobotService] = {}

    def add(self, robot_id: str, ip: str, **kwargs) -> RobotService:
        svc = RobotService(robot_id, ip)
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
