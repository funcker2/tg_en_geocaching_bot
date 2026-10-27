from datetime import datetime, timedelta, timezone

from handlers.player import PasswordThrottle, check_code, is_trusted_fix, render_target

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
M = 1 / 111_195  # degrees of latitude per metre

POINT = {"id": 1, "position": 1, "label": "Мост", "lat": 42.0, "lon": 25.0, "code": "Ёлка 7"}


def member(offset_m, accuracy=None, age_s=5, has_loc=True):
    if not has_loc:
        return {"last_lat": None, "last_lon": None, "last_accuracy": None, "last_loc_at": None}
    return {
        "last_lat": 42.0 + offset_m * M,
        "last_lon": 25.0,
        "last_accuracy": accuracy,
        "last_loc_at": (NOW - timedelta(seconds=age_s)).isoformat(),
    }


def test_check_code_ok_within_radius():
    assert check_code(member(14), POINT, "елка7", NOW) == "ok"


def test_check_code_far_strict():
    assert check_code(member(16), POINT, "елка7", NOW) == "far"


def test_check_code_accuracy_bonus():
    assert check_code(member(22, accuracy=8), POINT, "елка7", NOW) == "ok"


def test_check_code_wrong_far_is_far():
    assert check_code(member(500), POINT, "нет", NOW) == "far"


def test_check_code_wrong_near_is_wrong():
    assert check_code(member(5), POINT, "нет", NOW) == "wrong"


def test_is_trusted_fix():
    assert is_trusted_fix(5.0, False, False, False)
    assert not is_trusted_fix(None, False, False, False)  # map-picked pin
    assert not is_trusted_fix(5.0, True, False, False)  # forwarded
    assert not is_trusted_fix(5.0, False, True, False)  # venue
    assert is_trusted_fix(None, False, False, True)  # live tick


def test_check_code_stale():
    assert check_code(member(3, age_s=180), POINT, "елка7", NOW) == "stale"


def test_check_code_no_location():
    assert check_code(member(0, has_loc=False), POINT, "елка7", NOW) == "no_location"


def test_render_target_no_location():
    assert "трансляц" in render_target(member(0, has_loc=False), POINT)
    assert "трансляц" in render_target(None, POINT)


def test_render_target_with_location_and_none_label():
    text = render_target(member(340), {**POINT, "label": None})
    assert "339 м" in text and "↓ Ю" in text  # point is south of the member
    assert "None" not in text


def test_password_throttle():
    clock = [0.0]
    th = PasswordThrottle(clock=lambda: clock[0])
    for _ in range(5):
        th.record_fail(1)
    assert not th.is_blocked(1)  # 5 fails still allowed
    th.record_fail(1)
    assert th.is_blocked(1)  # more than 5
    assert not th.is_blocked(2)
    clock[0] = 601.0
    assert not th.is_blocked(1)  # window elapsed
