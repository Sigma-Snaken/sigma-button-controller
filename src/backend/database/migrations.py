import aiosqlite

MIGRATIONS = [
    # V1: Initial schema
    """
    CREATE TABLE IF NOT EXISTS robots (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        ip TEXT NOT NULL,
        enabled BOOLEAN DEFAULT 1,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS buttons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ieee_addr TEXT UNIQUE NOT NULL,
        name TEXT,
        paired_at TEXT NOT NULL,
        battery INTEGER,
        last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS bindings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        button_id INTEGER NOT NULL REFERENCES buttons(id) ON DELETE CASCADE,
        trigger TEXT NOT NULL CHECK(trigger IN ('single', 'double', 'long')),
        robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
        action TEXT NOT NULL,
        params TEXT DEFAULT '{}',
        enabled BOOLEAN DEFAULT 1,
        created_at TEXT,
        UNIQUE(button_id, trigger)
    );
    CREATE TABLE IF NOT EXISTS action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        button_id INTEGER,
        trigger TEXT,
        robot_id TEXT,
        action TEXT,
        params TEXT,
        result_ok BOOLEAN,
        result_detail TEXT,
        executed_at TEXT NOT NULL
    );
    """,
    # V2: Settings table for notifications etc.
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # V3: RTT logs for signal quality mapping
    """
    CREATE TABLE IF NOT EXISTS rtt_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        robot_name TEXT NOT NULL,
        serial TEXT,
        x REAL NOT NULL,
        y REAL NOT NULL,
        theta REAL NOT NULL,
        battery REAL,
        rtt_ms REAL NOT NULL,
        recorded_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_rtt_robot ON rtt_logs(robot_name);
    CREATE INDEX IF NOT EXISTS idx_rtt_time ON rtt_logs(recorded_at);
    """,
    # V4: Multi-stop route delivery
    """
    CREATE TABLE IF NOT EXISTS route_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        pinned_robot_id TEXT REFERENCES robots(id) ON DELETE SET NULL,
        stops TEXT NOT NULL DEFAULT '[]',
        default_timeout INTEGER NOT NULL DEFAULT 120,
        confirm_button_id INTEGER REFERENCES buttons(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS route_runs (
        id TEXT PRIMARY KEY,
        template_id TEXT REFERENCES route_templates(id) ON DELETE SET NULL,
        robot_id TEXT REFERENCES robots(id) ON DELETE SET NULL,
        stops TEXT NOT NULL DEFAULT '[]',
        default_timeout INTEGER NOT NULL DEFAULT 120,
        confirm_button_id INTEGER,
        status TEXT NOT NULL DEFAULT 'queued',
        current_stop INTEGER NOT NULL DEFAULT -1,
        started_at TEXT,
        completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_route_runs_status ON route_runs(status);
    CREATE INDEX IF NOT EXISTS idx_route_runs_robot ON route_runs(robot_id);
    CREATE TABLE IF NOT EXISTS route_stop_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL REFERENCES route_runs(id) ON DELETE CASCADE,
        stop_index INTEGER NOT NULL,
        location_name TEXT NOT NULL,
        arrived_at TEXT NOT NULL,
        confirmed_at TEXT,
        confirmed_by TEXT,
        timed_out BOOLEAN NOT NULL DEFAULT 0,
        departed_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_stop_logs_run ON route_stop_logs(run_id);
    """,
    # V5: Add shelf_name to route tables
    """
    ALTER TABLE route_templates ADD COLUMN shelf_name TEXT;
    ALTER TABLE route_runs ADD COLUMN shelf_name TEXT;
    """,
    # V6: Offline route execution mode
    """
    ALTER TABLE route_runs ADD COLUMN execution_mode TEXT DEFAULT 'online';
    """,
]


async def run_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _migrations (version INTEGER PRIMARY KEY)"
    )
    async with db.execute("SELECT COALESCE(MAX(version), 0) FROM _migrations") as cursor:
        current = (await cursor.fetchone())[0]
    for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                await db.execute(statement)
        await db.execute("INSERT INTO _migrations (version) VALUES (?)", (i,))
    await db.commit()
