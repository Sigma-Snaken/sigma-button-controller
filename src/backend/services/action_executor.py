import asyncio

from services.robot_manager import RobotManager
from utils.logger import get_logger

logger = get_logger("action_executor")


class ActionExecutor:
    def __init__(self, robot_manager: RobotManager):
        self._robot_manager = robot_manager

    async def execute(self, robot_id: str, action: str, params: dict) -> dict:
        svc = self._robot_manager.get(robot_id)
        if not svc:
            return {"ok": False, "error": f"Robot '{robot_id}' not found"}

        ctrl = svc.controller
        cmds = svc.commands

        if not ctrl and not cmds:
            return {"ok": False, "error": f"Robot '{robot_id}' not connected"}

        # Actions that RobotController supports (blocking — run in thread)
        ctrl_actions = {}
        if ctrl:
            ctrl_actions = {
                "move_to_location": lambda: ctrl.move_to_location(params["name"], timeout=120),
                "return_home": lambda: ctrl.return_home(timeout=60),
                "move_shelf": lambda: ctrl.move_shelf(params["shelf"], params["location"], timeout=120),
                "return_shelf": lambda: ctrl.return_shelf(params.get("shelf"), timeout=60),
            }

        # Actions that only KachakaCommands supports (fast, non-blocking)
        cmd_actions = {}
        if cmds:
            cmd_actions = {
                "speak": lambda: cmds.speak(params["text"]),
                "dock_shelf": lambda: cmds.dock_shelf(),
                "undock_shelf": lambda: cmds.undock_shelf(),
                "reset_shelf": lambda: cmds.reset_shelf_pose(params["shelf"]),
                "start_shortcut": lambda: cmds.start_shortcut(params["shortcut_id"]),
            }

        handler = ctrl_actions.get(action) or cmd_actions.get(action)
        if not handler:
            return {"ok": False, "error": f"Unknown action: {action}"}

        try:
            # Run blocking robot calls in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, handler)
            source = "controller" if action in ctrl_actions else "commands"
            logger.info(f"Executed {action} on {robot_id} via {source}: ok={result.get('ok')}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute {action} on {robot_id}: {e}")
            return {"ok": False, "error": str(e)}
