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
from services.button_manager import ButtonManager
from services.mqtt_service import MQTTService
from services.notifier import TelegramNotifier
from utils.logger import get_logger

logger = get_logger("main")

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "data/app.db")
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "data", exist_ok=True)
    await connect(db_path)
    db = get_db()
    await run_migrations(db)
    logger.info("Database connected and migrated")

    ws_manager = WSManager()
    robot_manager = RobotManager()
    action_executor = ActionExecutor(robot_manager)
    notifier = TelegramNotifier()
    button_manager = ButtonManager(db, action_executor, ws_manager, notifier)

    # Load telegram config from DB
    try:
        import json as _json
        async with db.execute("SELECT value FROM settings WHERE key = 'telegram_config'") as cursor:
            row = await cursor.fetchone()
        if row:
            cfg = _json.loads(row[0])
            notifier.configure(cfg.get("bot_token", ""), cfg.get("chat_id", ""))
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
        async for row in cursor:
            try:
                robot_manager.add(row[0], row[1])
            except Exception as e:
                logger.warning(f"Failed to connect robot {row[0]} at {row[1]}: {e}")

    _state.update({
        "db": db,
        "ws_manager": ws_manager,
        "robot_manager": robot_manager,
        "action_executor": action_executor,
        "button_manager": button_manager,
        "mqtt_service": mqtt_service,
        "notifier": notifier,
    })

    yield

    if mqtt_service:
        await mqtt_service.stop()
    robot_manager.stop_all()
    await disconnect()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

from routers import robots, buttons, bindings, logs, ws, monitor, settings  # noqa: E402
app.include_router(robots.router, prefix="/api")
app.include_router(buttons.router, prefix="/api")
app.include_router(bindings.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(ws.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
