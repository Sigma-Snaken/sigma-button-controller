import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database.connection import connect, disconnect, get_db
from database.migrations import run_migrations
from services.ws_manager import WSManager
from services.robot_manager import RobotManager
from services.action_executor import ActionExecutor
from services.command_queue import CommandQueue
from services.button_manager import ButtonManager
from services.mqtt_service import MQTTService
from services.notifier import TelegramNotifier
from services.rtt_logger import RTTLogger
from services.route_dispatcher import RouteDispatcher
from services.route_service import RouteService
from services.offline_route_generator import OfflineRouteGenerator
from services.offline_deployer import OfflineDeployer
from utils.logger import get_logger

logger = get_logger("main")

_state: dict = {}


async def _pose_broadcast_loop(robot_manager: RobotManager, ws_manager: WSManager):
    """Push pose updates for all connected robots every 1s via WebSocket."""
    while True:
        try:
            for robot_id in robot_manager.all_ids():
                svc = robot_manager.get(robot_id)
                if not svc or not svc.controller:
                    continue
                state = svc.controller.state
                if state is None or getattr(state, 'pose_x', None) is None:
                    continue
                await ws_manager.broadcast("robot:pose", {
                    "robot_id": robot_id,
                    "x": state.pose_x,
                    "y": state.pose_y,
                    "theta": state.pose_theta,
                    "battery": getattr(state, 'battery_pct', None),
                    "is_command_running": getattr(state, 'is_command_running', False),
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "data/app.db")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    logger.info("Database connected and migrated")

    ws_manager = WSManager()
    loop = asyncio.get_event_loop()
    robot_manager = RobotManager(ws_manager=ws_manager, loop=loop)
    action_executor = ActionExecutor(robot_manager)
    command_queue = CommandQueue(
        action_executor=action_executor,
        robot_manager=robot_manager,
        ws_manager=ws_manager,
        db=db,
    )
    notifier = TelegramNotifier()
    button_manager = ButtonManager(db, command_queue, ws_manager)

    route_dispatcher = RouteDispatcher(
        db=db, ws_manager=ws_manager, robot_manager=robot_manager,
    )
    route_service = RouteService(
        db=db, action_executor=action_executor,
        ws_manager=ws_manager, notifier=notifier,
    )
    route_dispatcher.set_route_service(route_service)
    route_service.set_dispatcher(route_dispatcher)
    button_manager.set_route_service(route_service)
    button_manager.set_route_dispatcher(route_dispatcher)

    offline_generator = OfflineRouteGenerator()
    offline_deployer = OfflineDeployer()
    route_dispatcher.set_offline_components(offline_generator, offline_deployer)

    # Load all settings from DB in one query
    try:
        import json as _json
        settings = {}
        async with db.execute("SELECT key, value FROM settings") as cursor:
            async for row in cursor:
                settings[row[0]] = row[1]
        if "route_mode" in settings:
            route_dispatcher.set_route_mode(settings["route_mode"])
        if "telegram_config" in settings:
            cfg = _json.loads(settings["telegram_config"])
            notifier.configure(cfg.get("bot_token", ""), cfg.get("chat_id", ""))
        if "queue_enabled" in settings:
            command_queue.set_enabled(settings["queue_enabled"] == "true")
    except Exception:
        pass

    mqtt_host = os.environ.get("MQTT_HOST", "")
    mqtt_service = None
    if mqtt_host:
        mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
        mqtt_service = MQTTService(host=mqtt_host, port=mqtt_port)
        mqtt_service.set_handler(button_manager.handle_message)
        await mqtt_service.start()

    async with db.execute("SELECT id, ip FROM robots WHERE enabled = 1") as cursor:
        rows = await cursor.fetchall()
    for robot_id, ip in rows:
        try:
            await loop.run_in_executor(None, robot_manager.add, robot_id, ip)
        except Exception as e:
            logger.warning(f"Failed to connect robot {robot_id} at {ip}: {e}")

    await route_dispatcher.rebuild_from_db()

    # Start RTT logger
    rtt_logger = RTTLogger(db, robot_manager, interval=5.0)
    try:
        async with db.execute("SELECT value FROM settings WHERE key = 'rtt_logger_enabled'") as cursor:
            row = await cursor.fetchone()
        if row:
            rtt_logger.set_enabled(row[0] == "true")
    except Exception:
        pass
    await rtt_logger.start()

    # Start pose broadcast (push controller.state via WebSocket every 1s)
    pose_task = asyncio.create_task(_pose_broadcast_loop(robot_manager, ws_manager))

    _state.update({
        "db": db,
        "ws_manager": ws_manager,
        "robot_manager": robot_manager,
        "action_executor": action_executor,
        "command_queue": command_queue,
        "button_manager": button_manager,
        "mqtt_service": mqtt_service,
        "notifier": notifier,
        "rtt_logger": rtt_logger,
        "route_dispatcher": route_dispatcher,
        "route_service": route_service,
        "offline_deployer": offline_deployer,
    })

    # Load Pi URL for offline route reports (already in settings dict from above)
    try:
        if settings.get("pi_url"):
            route_dispatcher.set_pi_url(settings["pi_url"])
    except NameError:
        pass

    yield

    pose_task.cancel()
    try:
        await pose_task
    except asyncio.CancelledError:
        pass
    await rtt_logger.stop()
    if mqtt_service:
        await mqtt_service.stop()
    robot_manager.stop_all()
    await disconnect()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from routers import robots, buttons, bindings, logs, ws, monitor, settings, wifi, queue, routes  # noqa: E402
app.include_router(robots.router, prefix="/api")
app.include_router(buttons.router, prefix="/api")
app.include_router(bindings.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(routes.router, prefix="/api")
app.include_router(wifi.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
