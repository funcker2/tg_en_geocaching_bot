import os
import aiosqlite
from config import DB_PATH


async def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS points (
                id            INTEGER PRIMARY KEY,
                lat           REAL,
                lon           REAL,
                photo_file_id TEXT,
                label         TEXT NOT NULL DEFAULT ''
            )
        """)
        for i in range(1, 6):
            await db.execute(
                "INSERT OR IGNORE INTO points (id, label) VALUES (?, ?)",
                (i, f"Точка {i}"),
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        INTEGER PRIMARY KEY,
                lang           TEXT,
                cooldown_until TEXT,
                last_lat       REAL,
                last_lon       REAL,
                created_at     TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id      INTEGER NOT NULL,
                point_id     INTEGER NOT NULL,
                activated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, point_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        await db.execute("INSERT OR IGNORE INTO settings VALUES ('refresh_delay_sec', '10')")
        await db.execute("INSERT OR IGNORE INTO settings VALUES ('activation_cooldown_min', '10')")

        # Migration: add lang column to existing deployments
        async with db.execute("PRAGMA table_info(users)") as cur:
            cols = [row[1] for row in await cur.fetchall()]
        if "lang" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN lang TEXT")

        await db.commit()


# ── Points ────────────────────────────────────────────────────────────────────

async def get_points() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM points ORDER BY id") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_point(point_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM points WHERE id = ?", (point_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_point_coords(point_id: int, lat: float, lon: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE points SET lat = ?, lon = ? WHERE id = ?", (lat, lon, point_id)
        )
        await db.commit()


async def update_point_photo(point_id: int, photo_file_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE points SET photo_file_id = ? WHERE id = ?", (photo_file_id, point_id)
        )
        await db.commit()


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            return dict(await cur.fetchone())


async def update_user_location(user_id: int, lat: float, lon: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_lat = ?, last_lon = ? WHERE user_id = ?",
            (lat, lon, user_id),
        )
        await db.commit()


async def set_user_cooldown(user_id: int, until_iso: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET cooldown_until = ? WHERE user_id = ?",
            (until_iso, user_id),
        )
        await db.commit()


async def reset_user_cooldown(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET cooldown_until = NULL WHERE user_id = ?", (user_id,)
        )
        await db.commit()


async def set_user_lang(user_id: int, lang: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET lang = ? WHERE user_id = ?", (lang, user_id)
        )
        await db.commit()


async def reset_user_progress(user_id: int) -> None:
    """Wipe cooldown + all activated points so the player starts fresh."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET cooldown_until = NULL WHERE user_id = ?", (user_id,)
        )
        await db.execute(
            "DELETE FROM user_points WHERE user_id = ?", (user_id,)
        )
        await db.commit()


# ── Activations ───────────────────────────────────────────────────────────────

async def record_activation(user_id: int, point_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_points (user_id, point_id) VALUES (?, ?)",
            (user_id, point_id),
        )
        await db.commit()


async def get_user_activated_points(user_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT point_id FROM user_points WHERE user_id = ?", (user_id,)
        ) as cur:
            return [row[0] for row in await cur.fetchall()]


# ── Admin helpers ─────────────────────────────────────────────────────────────

async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.*,
                   COUNT(up.point_id) AS points_count
              FROM users u
              LEFT JOIN user_points up ON u.user_id = up.user_id
             GROUP BY u.user_id
             ORDER BY u.created_at DESC
        """) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Settings ──────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value)
        )
        await db.commit()
