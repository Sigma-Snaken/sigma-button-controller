import aiosqlite

_db: aiosqlite.Connection | None = None
_db_path: str = "data/app.db"


async def connect(db_path: str | None = None) -> None:
    global _db, _db_path
    if db_path:
        _db_path = db_path
    _db = await aiosqlite.connect(_db_path)
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.execute("PRAGMA foreign_keys=ON")


def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("Database not connected. Call connect() first.")
    return _db


async def disconnect() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
