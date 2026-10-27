import aiosqlite
import pytest

import db


@pytest.fixture(autouse=True)
async def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "sub" / "t.db"))
    await db.init_db()


async def _raw_team(name, password, is_test=0):
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO teams (name, password, is_test) VALUES (?, ?, ?)",
            (name, password, is_test),
        )
        await conn.commit()
        return cur.lastrowid


async def _labels():
    return [p["label"] for p in await db.get_points()]


async def test_points_order_and_move():
    a = await db.add_point("A", 1.0, 1.0, "a")
    await db.add_point("B", 1.0, 1.0, "b")
    c = await db.add_point("C", 1.0, 1.0, "c")
    await db.move_point(c, -1)
    assert await _labels() == ["A", "C", "B"]
    await db.move_point(a, -1)
    assert await _labels() == ["A", "C", "B"]
    await db.move_point(c, 1)
    assert await _labels() == ["A", "B", "C"]


async def test_delete_renumbers():
    await db.add_point("A", 1.0, 1.0, "a")
    b = await db.add_point("B", 1.0, 1.0, "b")
    await db.add_point("C", 1.0, 1.0, "c")
    await db.delete_point(b)
    pts = await db.get_points()
    assert [p["position"] for p in pts] == [1, 2]
    assert [p["label"] for p in pts] == ["A", "C"]


async def test_join_sets_start_once():
    team = (await db.create_teams(1))[0]
    r1 = await db.join_team(10, team["id"], "t1")
    assert r1["started_at"] == "t1"
    r2 = await db.join_team(11, team["id"], "t2")
    assert r2["started_at"] == "t1"
    assert sorted(await db.get_team_member_ids(team["id"])) == [10, 11]


async def test_password_lookup_normalized():
    tid = await _raw_team("X", "тигр-42")
    found = await db.get_team_by_password("  ТИГР-42 ")
    assert found["id"] == tid
    assert await db.get_team_by_password("нет-00") is None


async def test_create_teams_unique_passwords():
    first = await db.create_teams(10)
    second = await db.create_teams(10)
    teams = first + second
    assert len({x["password"] for x in teams}) == 20
    assert [x["name"] for x in await db.list_teams()] == [f"Команда {i}" for i in range(1, 21)]


async def test_advance_team_only_once():
    team = (await db.create_teams(1))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    await db.add_point("B", 1.0, 1.0, "b")
    res = await db.advance_team(team["id"], 1, p1, 5, "t1", 2)
    assert res is not None and res["current_position"] == 2
    assert await db.advance_team(team["id"], 1, p1, 6, "t2", 2) is None
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM team_points")
        assert (await cur.fetchone())[0] == 1


async def test_advance_last_sets_finished():
    team = (await db.create_teams(1))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    res = await db.advance_team(team["id"], 1, p1, 5, "t9", 1)
    assert res["finished_at"] == "t9"


async def test_advance_after_finish_returns_none():
    team = (await db.create_teams(1))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    await db.advance_team(team["id"], 1, p1, 5, "t9", 1)
    cur = await db.get_team(team["id"])
    assert await db.advance_team(team["id"], cur["current_position"], p1, 5, "t10", 1) is None


async def test_current_point_after_delete():
    team = (await db.create_teams(1))[0]
    await db.add_point("A", 1.0, 1.0, "a")
    await db.add_point("B", 1.0, 1.0, "b")
    c = await db.add_point("C", 1.0, 1.0, "c")
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute("UPDATE teams SET current_position=3 WHERE id=?", (team["id"],))
        await conn.commit()
    team = await db.get_team(team["id"])
    assert (await db.get_current_point(team))["label"] == "C"
    await db.delete_point(c)
    assert await db.get_current_point(team) is None


async def test_reset_test_only():
    real = (await db.create_teams(1))[0]
    test = (await db.create_teams(1, is_test=True))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    for t_ in (real, test):
        await db.join_team(1000 + t_["id"], t_["id"], "s")
        await db.advance_team(t_["id"], 1, p1, 1, "x", 5)
    await db.reset_progress(True)
    real2, test2 = await db.get_team(real["id"]), await db.get_team(test["id"])
    assert real2["current_position"] == 2 and real2["started_at"] == "s"
    assert test2["current_position"] == 1 and test2["started_at"] is None
    assert await db.get_member(1000 + test["id"]) is not None
    await db.reset_progress(False)
    real3 = await db.get_team(real["id"])
    assert real3["current_position"] == 1 and real3["started_at"] is None


async def test_results_exclude_test():
    real = (await db.create_teams(1))[0]
    test = (await db.create_teams(1, is_test=True))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    await db.advance_team(real["id"], 1, p1, 1, "t5", 3)
    res = await db.get_results()
    assert [r["id"] for r in res] == [real["id"]]
    assert res[0]["taken_count"] == 1 and res[0]["last_taken_at"] == "t5"
    assert res[0]["taken"] == [{"label": "A", "taken_at": "t5"}]
    allr = await db.get_results(include_test=True)
    assert {r["id"] for r in allr} == {real["id"], test["id"]}


async def test_settings_and_members():
    assert await db.get_setting("final_hint") == ""
    await db.set_setting("final_hint", "под лавкой")
    assert await db.get_setting("final_hint") == "под лавкой"
    team = (await db.create_teams(1))[0]
    await db.join_team(7, team["id"], "t")
    await db.update_member_location(7, 1.5, 2.5, 8.0, "L")
    m = await db.get_member(7)
    assert (m["last_lat"], m["last_accuracy"], m["last_loc_at"]) == (1.5, 8.0, "L")
    await db.leave_team(7)
    assert await db.get_member(7) is None
    await db.join_team(7, team["id"], "t")
    await db.delete_team(team["id"])
    assert await db.get_member(7) is None and await db.get_team(team["id"]) is None


async def test_live_until_stored_and_migrated(tmp_path, monkeypatch):
    team = (await db.create_teams(1))[0]
    await db.join_team(7, team["id"], "t")
    await db.update_member_location(7, 1.5, 2.5, 8.0, "L", live_until_iso="U")
    assert (await db.get_member(7))["live_until"] == "U"
    await db.update_member_location(7, 1.5, 2.5, 8.0, "L2")
    assert (await db.get_member(7))["live_until"] is None
    # an old v2 database without the column gets it added by init_db
    old = str(tmp_path / "old.db")
    async with aiosqlite.connect(old) as conn:
        await conn.execute("CREATE TABLE members (user_id INTEGER PRIMARY KEY, team_id INTEGER, "
                           "last_lat REAL, last_lon REAL, last_accuracy REAL, last_loc_at TEXT)")
        await conn.commit()
    monkeypatch.setattr(db, "DB_PATH", old)
    await db.init_db()
    await db.init_db()  # idempotent
    async with aiosqlite.connect(old) as conn:
        cur = await conn.execute("PRAGMA table_info(members)")
        assert "live_until" in [r[1] for r in await cur.fetchall()]


async def test_ensure_started_after_reset():
    team = (await db.create_teams(1))[0]
    await db.join_team(7, team["id"], "t1")
    await db.reset_progress(False)
    assert (await db.get_team(team["id"]))["started_at"] is None
    await db.ensure_started(team["id"], "t2")
    assert (await db.get_team(team["id"]))["started_at"] == "t2"
    await db.ensure_started(team["id"], "t3")  # never overwrites
    assert (await db.get_team(team["id"]))["started_at"] == "t2"


async def test_advance_fills_missing_start():
    team = (await db.create_teams(1))[0]
    p1 = await db.add_point("A", 1.0, 1.0, "a")
    await db.add_point("B", 1.0, 1.0, "b")
    res = await db.advance_team(team["id"], 1, p1, 5, "t1", 2)
    assert res["started_at"] == "t1"
    p2 = (await db.get_points())[1]["id"]
    res = await db.advance_team(team["id"], 2, p2, 5, "t2", 2)
    assert res["started_at"] == "t1" and res["finished_at"] == "t2"


async def test_advance_after_point_reordered_ahead():
    team = (await db.create_teams(1))[0]
    a = await db.add_point("A", 1.0, 1.0, "a")
    await db.add_point("B", 1.0, 1.0, "b")
    await db.add_point("C", 1.0, 1.0, "c")
    await db.advance_team(team["id"], 1, a, 5, "t1", 3)
    await db.move_point(a, 1)  # admin moves the taken point ahead: B, A, C
    res = await db.advance_team(team["id"], 2, a, 6, "t2", 3)
    assert res is not None and res["current_position"] == 3
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cur = await conn.execute("SELECT taken_at, taken_by FROM team_points WHERE point_id = ?", (a,))
        assert await cur.fetchall() == [("t2", 6)]
