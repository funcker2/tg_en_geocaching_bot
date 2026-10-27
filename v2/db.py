import os
import random
import re

import aiosqlite

import config
from game import generate_passwords, normalize_code

# Kept as a module global so tests can monkeypatch `db.DB_PATH`.
DB_PATH = config.DB_PATH

# ── Schema ────────────────────────────────────────────────────────────────────


async def init_db() -> None:
    dirname = os.path.dirname(DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS points (
                id       INTEGER PRIMARY KEY,
                position INTEGER NOT NULL,
                label    TEXT,
                lat      REAL,
                lon      REAL,
                code     TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id               INTEGER PRIMARY KEY,
                name             TEXT,
                password         TEXT UNIQUE,
                is_test          INTEGER DEFAULT 0,
                started_at       TEXT,
                finished_at      TEXT,
                current_position INTEGER NOT NULL DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id       INTEGER PRIMARY KEY,
                team_id       INTEGER,
                last_lat      REAL,
                last_lon      REAL,
                last_accuracy REAL,
                last_loc_at   TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS team_points (
                team_id  INTEGER NOT NULL,
                point_id INTEGER NOT NULL,
                taken_at TEXT,
                taken_by INTEGER,
                PRIMARY KEY (team_id, point_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('final_hint', '')")
        await db.commit()


# ── Points ────────────────────────────────────────────────────────────────────


async def get_points() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM points ORDER BY position")
        return [dict(r) for r in await cur.fetchall()]


async def get_point(point_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM points WHERE id = ?", (point_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_point(label: str, lat: float, lon: float, code: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM points")
        position = (await cur.fetchone())[0]
        cur = await db.execute(
            "INSERT INTO points (position, label, lat, lon, code) VALUES (?, ?, ?, ?, ?)",
            (position, label, lat, lon, code),
        )
        await db.commit()
        return cur.lastrowid


_POINT_FIELDS = {"label", "lat", "lon", "code"}


async def update_point(point_id: int, **fields) -> None:
    unknown = set(fields) - _POINT_FIELDS
    if unknown:
        raise ValueError(f"unknown point fields: {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE points SET {assignments} WHERE id = ?",
            (*fields.values(), point_id),
        )
        await db.commit()


async def delete_point(point_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM points WHERE id = ?", (point_id,))
        cur = await db.execute("SELECT id FROM points ORDER BY position")
        for position, row in enumerate(await cur.fetchall(), start=1):
            await db.execute("UPDATE points SET position = ? WHERE id = ?", (position, row[0]))
        await db.commit()


async def move_point(point_id: int, delta: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT position FROM points WHERE id = ?", (point_id,))
        row = await cur.fetchone()
        if row is None:
            return
        position = row[0]
        cur = await db.execute("SELECT id, position FROM points WHERE position = ?", (position + delta,))
        neighbour = await cur.fetchone()
        if neighbour is None or delta == 0:
            return
        await db.execute("UPDATE points SET position = ? WHERE id = ?", (neighbour[1], point_id))
        await db.execute("UPDATE points SET position = ? WHERE id = ?", (position, neighbour[0]))
        await db.commit()


async def get_current_point(team: dict) -> dict | None:
    """Point at the team's current position; None means the route is complete."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM points WHERE position = ?", (team["current_position"],))
        row = await cur.fetchone()
        return dict(row) if row else None


# ── Teams ─────────────────────────────────────────────────────────────────────


async def create_teams(n: int, is_test: bool = False) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT name, password FROM teams")
        existing = await cur.fetchall()
        used = {r["password"] for r in existing}
        numbers = [int(m.group(1)) for r in existing if r["name"] and (m := re.fullmatch(r"Команда (\d+)", r["name"]))]
        next_number = max(numbers, default=0) + 1

        rng = random.SystemRandom()
        passwords: list[str] = []
        while len(passwords) < n:
            # Raises ValueError if a batch of this size is impossible.
            for pwd in generate_passwords(n, rng):
                pwd = normalize_code(pwd)
                if pwd not in used and len(passwords) < n:
                    used.add(pwd)
                    passwords.append(pwd)
            if len(passwords) < n and len(used) >= 4000:
                raise ValueError("не хватает свободных паролей")

        created = []
        for offset, pwd in enumerate(passwords):
            cur = await db.execute(
                "INSERT INTO teams (name, password, is_test) VALUES (?, ?, ?)",
                (f"Команда {next_number + offset}", pwd, int(is_test)),
            )
            created.append(cur.lastrowid)
        await db.commit()
        if not created:
            return []
        marks = ",".join("?" * len(created))
        cur = await db.execute(f"SELECT * FROM teams WHERE id IN ({marks}) ORDER BY id", created)
        return [dict(r) for r in await cur.fetchall()]


async def get_team(team_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_team_by_password(password: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM teams WHERE password = ?", (normalize_code(password),))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_teams() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM teams ORDER BY id")
        return [dict(r) for r in await cur.fetchall()]


async def rename_team(team_id: int, name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team_id))
        await db.commit()


async def delete_team(team_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM members WHERE team_id = ?", (team_id,))
        await db.execute("DELETE FROM team_points WHERE team_id = ?", (team_id,))
        await db.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        await db.commit()


# ── Members ───────────────────────────────────────────────────────────────────


async def join_team(user_id: int, team_id: int, now_iso: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO members (user_id, team_id) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET team_id = excluded.team_id",
            (user_id, team_id),
        )
        await db.execute(
            "UPDATE teams SET started_at = ? WHERE id = ? AND started_at IS NULL",
            (now_iso, team_id),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        return dict(await cur.fetchone())


async def leave_team(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM members WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_member(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM members WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_team_member_ids(team_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM members WHERE team_id = ? ORDER BY user_id", (team_id,))
        return [r[0] for r in await cur.fetchall()]


async def update_member_location(user_id: int, lat: float, lon: float, accuracy: float | None, loc_at_iso: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET last_lat = ?, last_lon = ?, last_accuracy = ?, last_loc_at = ? WHERE user_id = ?",
            (lat, lon, accuracy, loc_at_iso, user_id),
        )
        await db.commit()


# ── Progress ──────────────────────────────────────────────────────────────────


async def advance_team(
    team_id: int, expected_position: int, point_id: int, user_id: int, now_iso: str, total_points: int
) -> dict | None:
    """Atomically move the team forward; None if someone else already did."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if expected_position == total_points:
            cur = await db.execute(
                "UPDATE teams SET current_position = current_position + 1, finished_at = ? "
                "WHERE id = ? AND current_position = ? AND finished_at IS NULL",
                (now_iso, team_id, expected_position),
            )
        else:
            cur = await db.execute(
                "UPDATE teams SET current_position = current_position + 1 "
                "WHERE id = ? AND current_position = ? AND finished_at IS NULL",
                (team_id, expected_position),
            )
        if cur.rowcount != 1:
            await db.rollback()
            return None
        await db.execute(
            "INSERT INTO team_points (team_id, point_id, taken_at, taken_by) VALUES (?, ?, ?, ?)",
            (team_id, point_id, now_iso, user_id),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
        return dict(await cur.fetchone())


async def get_results(include_test: bool = False) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "" if include_test else "WHERE is_test = 0"
        cur = await db.execute(f"SELECT id, name, started_at, finished_at FROM teams {where} ORDER BY id")
        results = []
        for team in await cur.fetchall():
            cur = await db.execute(
                "SELECT p.label AS label, tp.taken_at AS taken_at FROM team_points tp "
                "LEFT JOIN points p ON p.id = tp.point_id "
                "WHERE tp.team_id = ? ORDER BY tp.taken_at, tp.rowid",
                (team["id"],),
            )
            taken = [dict(r) for r in await cur.fetchall()]
            results.append({
                **dict(team),
                "taken_count": len(taken),
                "last_taken_at": taken[-1]["taken_at"] if taken else None,
                "taken": taken,
            })
        return results


async def reset_progress(test_only: bool) -> None:
    """test_only=True resets only test teams; False resets all non-test teams."""
    flag = 1 if test_only else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM team_points WHERE team_id IN (SELECT id FROM teams WHERE is_test = ?)", (flag,)
        )
        await db.execute(
            "UPDATE teams SET started_at = NULL, finished_at = NULL, current_position = 1 WHERE is_test = ?",
            (flag,),
        )
        await db.commit()


# ── Settings ──────────────────────────────────────────────────────────────────


async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else ""


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
