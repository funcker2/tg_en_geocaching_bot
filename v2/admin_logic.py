"""Pure helpers for the admin panel (no aiogram / DB dependencies)."""
import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from game import fmt_duration, rank_results

MAX_MESSAGE_CHARS = 3800  # Telegram limit is 4096; leave room for <pre> tags
MAX_TEAMS_AT_ONCE = 50


def parse_coords(text: str) -> tuple[float, float] | None:
    """Parse 'lat lon', 'lat, lon', 'lat; lon' or decimal commas ('55,1 37,2')."""
    parts = [p for p in re.split(r"[\s,;]+", text.strip()) if p]
    if len(parts) != 2:
        # "55,1 37,2" style: split on whitespace only, comma is the decimal mark
        parts = text.split()
        if len(parts) != 2:
            return None
    try:
        lat = float(parts[0].replace(",", "."))
        lon = float(parts[1].replace(",", "."))
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def parse_count(text: str, maximum: int = MAX_TEAMS_AT_ONCE) -> int | None:
    text = text.strip()
    if not text.isdigit():
        return None
    n = int(text)
    return n if 1 <= n <= maximum else None


def fmt_local(iso: str | None, tz_name: str) -> str:
    """UTC ISO timestamp -> HH:MM in tz_name ('—' for None)."""
    if not iso:
        return "—"
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(tz_name)).strftime("%H:%M")


def _elapsed(row: dict) -> str:
    if not row["started_at"] or not row["finished_at"]:
        return "—"
    start = datetime.fromisoformat(row["started_at"])
    end = datetime.fromisoformat(row["finished_at"])
    return fmt_duration(int((end - start).total_seconds()))


def format_results(rows: list[dict], tz_name: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Ranked results as one or more HTML messages with <pre> tables."""
    ranked = rank_results(rows)
    if not ranked:
        return ["Пока нет команд."]
    header = "№  Команда          Старт  Финиш  Время    Точек"
    lines = []
    for place, row in enumerate(ranked, start=1):
        name = html.escape((row["name"] or "—")[:16])
        lines.append(
            f"{place:<2} {name:<16} {fmt_local(row['started_at'], tz_name):<6} "
            f"{fmt_local(row['finished_at'], tz_name):<6} {_elapsed(row):<8} {row['taken_count']}"
        )
    chunks: list[list[str]] = [[]]
    size = len(header)
    for line in lines:
        if size + len(line) + 1 > limit and chunks[-1]:
            chunks.append([])
            size = len(header)
        chunks[-1].append(line)
        size += len(line) + 1
    return ["<pre>" + "\n".join([header, *chunk]) + "</pre>" for chunk in chunks]


def _pack(parts: list[str], sep: str, limit: int) -> list[str]:
    """Greedily join parts with sep into strings no longer than limit."""
    packed: list[str] = []
    for part in parts:
        if packed and len(packed[-1]) + len(sep) + len(part) <= limit:
            packed[-1] += sep + part
        else:
            packed.append(part)
    return packed


def format_breakdown(rows: list[dict], tz_name: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Per-team point times, in ranked order, as HTML messages:
    '<b>Команда 1</b>: 1) Мост 13:20, 2) Парк 14:30'. Long lines wrap at ', '."""
    ranked = rank_results(rows)
    if not ranked:
        return []
    lines = ["🕒 <b>Время взятия точек</b>"]
    for row in ranked:
        head = f"<b>{html.escape(row['name'] or '—')}</b>: "
        items = [
            f"{n}) {html.escape(item['label'] or 'без названия')} {fmt_local(item['taken_at'], tz_name)}"
            for n, item in enumerate(row.get("taken") or [], start=1)
        ]
        if not items:
            lines.append(head + "—")
            continue
        items[0] = head + items[0]
        lines.extend(_pack(items, ", ", limit))
    return _pack(lines, "\n", limit)
