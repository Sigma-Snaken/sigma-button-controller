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
