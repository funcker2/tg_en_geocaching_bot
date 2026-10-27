import random
import re
from datetime import datetime, timezone
from math import atan2, cos, degrees, radians, sin

from config import ACCURACY_BONUS_CAP_M, ACTIVATION_RADIUS_M, LIVE_FRESH_MAX_S, LOCATION_STALE_S

# ── Codes ─────────────────────────────────────────────────────────────────────


def normalize_code(s: str) -> str:
    """Lower-case, ё→е, drop all whitespace — so codes compare leniently."""
    return re.sub(r"\s+", "", s.lower().replace("ё", "е"))


def normalize_password(s: str) -> str:
    """Like normalize_code but also drops punctuation/underscores, so a dictated
    'яблоко 42', 'яблоко42' and 'ЯБЛОКО-42' all match 'яблоко-42'."""
    return re.sub(r"[\W_]+", "", s.lower().replace("ё", "е"))


# ── Location ──────────────────────────────────────────────────────────────────


def effective_radius(accuracy: float | None) -> float:
    """Activation radius: base plus capped GPS-accuracy bonus (none if unknown)."""
    if accuracy is None or accuracy <= 0:
        return ACTIVATION_RADIUS_M
    return ACTIVATION_RADIUS_M + min(accuracy, ACCURACY_BONUS_CAP_M)


def _parse_utc(iso: str) -> datetime:
    parsed = datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_stale(loc_at_iso: str | None, now: datetime) -> bool:
    """True if there is no fix or it is older than LOCATION_STALE_S seconds."""
    if loc_at_iso is None:
        return True
    return (now - _parse_utc(loc_at_iso)).total_seconds() > LOCATION_STALE_S


def is_fresh_fix(loc_at_iso: str | None, live_until_iso: str | None, now: datetime) -> bool:
    """Fix usable for a code check: younger than LOCATION_STALE_S, or — while
    live sharing is still running (now < live_until) — younger than
    LIVE_FRESH_MAX_S, since a parked phone sends no live updates."""
    if not is_stale(loc_at_iso, now):
        return True
    if loc_at_iso is None or live_until_iso is None or now >= _parse_utc(live_until_iso):
        return False
    return (now - _parse_utc(loc_at_iso)).total_seconds() <= LIVE_FRESH_MAX_S


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees 0..360."""
    φ1, φ2 = radians(lat1), radians(lat2)
    dλ = radians(lon2 - lon1)
    y = sin(dλ) * cos(φ2)
    x = cos(φ1) * sin(φ2) - sin(φ1) * cos(φ2) * cos(dλ)
    return (degrees(atan2(y, x)) + 360) % 360


_DIRECTIONS = ["↑ С", "↗ СВ", "→ В", "↘ ЮВ", "↓ Ю", "↙ ЮЗ", "← З", "↖ СЗ"]


def direction_label(deg: float) -> str:
    """Arrow + compass label for a bearing, 45° sectors centred on directions."""
    return _DIRECTIONS[int(((deg % 360) + 22.5) // 45) % 8]


# ── Formatting ────────────────────────────────────────────────────────────────


def fmt_dist(m: float) -> str:
    """'340 м' below 1 km, otherwise '1.2 км'."""
    return f"{int(m)} м" if m < 1000 else f"{m / 1000:.1f} км"


def fmt_duration(seconds: int) -> str:
    """Seconds as h:mm:ss."""
    h, rest = divmod(max(0, int(seconds)), 3600)
    mins, secs = divmod(rest, 60)
    return f"{h}:{mins:02d}:{secs:02d}"


# ── Passwords ─────────────────────────────────────────────────────────────────

_WORDS = [
    "яблоко", "груша", "слива", "вишня", "лимон", "арбуз", "дыня", "морковь",
    "капуста", "огурец", "редис", "лук", "чеснок", "гриб", "орех", "суп",
    "хлеб", "сыр", "молоко", "чай", "кофе", "стол", "стул", "окно",
    "дверь", "лампа", "книга", "ручка", "часы", "ключ", "зонт", "мост",
    "река", "озеро", "гора", "лес", "поле", "ветер", "дождь", "снег",
]


def generate_passwords(n: int, rng: random.Random) -> list[str]:
    """Return n unique passwords of the form '<слово>-<две цифры>'."""
    if n > len(_WORDS) * 100:
        raise ValueError("слишком много паролей запрошено")
    seen: set[str] = set()
    result: list[str] = []
    while len(result) < n:
        pwd = f"{rng.choice(_WORDS)}-{rng.randrange(100):02d}"
        if pwd not in seen:
            seen.add(pwd)
            result.append(pwd)
    return result


# ── Ranking ───────────────────────────────────────────────────────────────────


def _parse(iso: str) -> datetime:
    parsed = datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def rank_results(rows: list[dict]) -> list[dict]:
    """Sort teams: finishers by elapsed time, then by points taken (desc) and
    earliest last take; teams that never started go last."""
    finished, active, idle = [], [], []
    for row in rows:
        if row["started_at"] is None:
            idle.append(row)
        elif row["finished_at"] is not None:
            finished.append(row)
        else:
            active.append(row)
    finished.sort(key=lambda r: _parse(r["finished_at"]) - _parse(r["started_at"]))
    active.sort(key=lambda r: (
        -r["taken_count"],
        _parse(r["last_taken_at"]) if r["last_taken_at"] else datetime.max.replace(tzinfo=timezone.utc),
    ))
    return finished + active + idle
