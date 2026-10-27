import random
import re
from datetime import datetime, timedelta, timezone

from game import (
    bearing_deg,
    direction_label,
    effective_radius,
    fmt_dist,
    fmt_duration,
    generate_passwords,
    is_fresh_fix,
    is_stale,
    normalize_code,
    normalize_password,
    rank_results,
)


def test_normalize_code():
    assert normalize_code("  Ёлка 12 ") == "елка12"
    assert normalize_code("ABC") == "abc"


def test_effective_radius_none():
    assert effective_radius(None) == 15
    assert effective_radius(0) == 15


def test_effective_radius_capped():
    assert effective_radius(4) == 19
    assert effective_radius(50) == 25


def test_is_stale():
    now = datetime.now(timezone.utc)
    assert is_stale(None, now) is True
    assert is_stale((now - timedelta(seconds=119)).isoformat(), now) is False
    assert is_stale((now - timedelta(seconds=121)).isoformat(), now) is True


def test_is_stale_naive_treated_as_utc():
    now = datetime.now(timezone.utc)
    naive = (now - timedelta(seconds=10)).replace(tzinfo=None).isoformat()
    assert is_stale(naive, now) is False


def test_direction_label():
    assert direction_label(0) == "↑ С"
    assert direction_label(44) == "↗ СВ"
    assert direction_label(350) == "↑ С"
    assert direction_label(180) == "↓ Ю"


def test_bearing_north():
    assert abs(bearing_deg(42.0, 25.0, 42.01, 25.0)) < 1 or abs(bearing_deg(42.0, 25.0, 42.01, 25.0) - 360) < 1


def test_bearing_east():
    assert abs(bearing_deg(0.0, 0.0, 0.0, 1.0) - 90) < 1


def test_generate_passwords_unique():
    pwds = generate_passwords(30, random.Random(1))
    assert len(set(pwds)) == 30
    assert all(re.match(r"^[а-я]+-\d{2}$", p) for p in pwds)


def test_generate_passwords_many():
    assert len(set(generate_passwords(500, random.Random(2)))) == 500


def test_rank_results():
    t0 = "2026-01-01T10:00:00+00:00"
    rows = [
        {"name": "c3", "started_at": t0, "finished_at": None, "taken_count": 3, "last_taken_at": t0},
        {"name": "never", "started_at": None, "finished_at": None, "taken_count": 0, "last_taken_at": None},
        {"name": "c5", "started_at": t0, "finished_at": None, "taken_count": 5, "last_taken_at": t0},
        {"name": "f2", "started_at": t0, "finished_at": "2026-01-01T12:00:00+00:00", "taken_count": 9, "last_taken_at": t0},
        {"name": "f1", "started_at": t0, "finished_at": "2026-01-01T11:00:00+00:00", "taken_count": 9, "last_taken_at": t0},
    ]
    assert [r["name"] for r in rank_results(rows)] == ["f1", "f2", "c5", "c3", "never"]


def test_fmt_duration():
    assert fmt_duration(3909) == "1:05:09"


def test_fmt_dist():
    assert fmt_dist(340) == "340 м"
    assert fmt_dist(1200) == "1.2 км"


def test_generate_passwords_charset():
    assert all(re.match(r"^[а-я]+-\d{2}$", p) for p in generate_passwords(2000, random.Random(3)))


def test_is_fresh_fix_live_window():
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    ago = lambda s: (now - timedelta(seconds=s)).isoformat()
    live_on = (now + timedelta(hours=1)).isoformat()
    live_off = (now - timedelta(minutes=1)).isoformat()
    assert is_fresh_fix(ago(300), live_on, now) is True  # live active, 5 min old
    assert is_fresh_fix(ago(660), live_on, now) is False  # live active, 11 min old
    assert is_fresh_fix(ago(180), live_off, now) is False  # live expired, 3 min old
    assert is_fresh_fix(ago(60), None, now) is True  # no live, 1 min old
    assert is_fresh_fix(ago(180), None, now) is False
    assert is_fresh_fix(None, live_on, now) is False


def test_normalize_password_dictation():
    target = normalize_password("яблоко-42")
    for typed in ("яблоко 42", "яблоко42", "ЯБЛОКО-42", " Яблоко_42. ", "яблоко—42"):
        assert normalize_password(typed) == target
    assert normalize_password("ёлка-01") == normalize_password("елка 01")
    assert normalize_password("яблоко-43") != target
