import asyncio
import html
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import Message

import db
import texts
from config import LIVE_EDIT_MIN_INTERVAL_S
from game import (
    bearing_deg,
    direction_label,
    effective_radius,
    fmt_dist,
    fmt_duration,
    is_fresh_fix,
    normalize_code,
)
from keyboards import location_keyboard
from states import PlayerLogin
from utils.geo import haversine_m

player_router = Router()
log = logging.getLogger(__name__)

# ── Password brute-force throttle ─────────────────────────────────────────────

PASSWORD_MAX_FAILS = 5
PASSWORD_WINDOW_S = 600.0


class PasswordThrottle:
    """Per-user in-memory limiter: more than PASSWORD_MAX_FAILS wrong passwords
    inside PASSWORD_WINDOW_S blocks checking until old failures age out."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._fails: dict[int, deque[float]] = {}

    def _prune(self, user_id: int) -> deque[float]:
        q = self._fails.setdefault(user_id, deque())
        cutoff = self._clock() - PASSWORD_WINDOW_S
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def is_blocked(self, user_id: int) -> bool:
        return len(self._prune(user_id)) > PASSWORD_MAX_FAILS

    def record_fail(self, user_id: int) -> None:
        self._prune(user_id).append(self._clock())

    def reset(self, user_id: int) -> None:
        self._fails.pop(user_id, None)


_throttle = PasswordThrottle()

# ── Live-location state (in-process) ──────────────────────────────────────────
# user_id -> (chat_id, message_id, position of the point it was rendered for)
_live_msg: dict[int, tuple[int, int, int]] = {}
_live_last_edit: dict[int, float] = {}

# ── Pure helpers ──────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _label(point: dict) -> str:
    return html.escape(point.get("label") or texts.POINT_NO_LABEL)


def render_target(member: dict | None, point: dict) -> str:
    """Point header + direction/distance from the member's last fix."""
    head = texts.POINT_HEADER.format(n=point["position"], label=_label(point))
    if member is None or member.get("last_lat") is None or member.get("last_lon") is None:
        return f"{head}\n{texts.NO_LOCATION}"
    if point.get("lat") is None or point.get("lon") is None:
        return f"{head}\n{texts.NO_COORDS}"
    lat, lon = member["last_lat"], member["last_lon"]
    dist = haversine_m(lat, lon, point["lat"], point["lon"])
    direction = direction_label(bearing_deg(lat, lon, point["lat"], point["lon"]))
    lines = [head, texts.DIRECTION_LINE.format(direction=direction, dist=fmt_dist(dist))]
    acc = member.get("last_accuracy")
    if acc:
        lines.append(texts.ACCURACY_LINE.format(acc=int(acc)))
    return "\n".join(lines)


def check_code(member: dict, point: dict, code: str, now: datetime) -> str:
    """'ok' | 'wrong' | 'no_location' | 'stale' | 'far'.

    Order: location present -> fresh -> within radius -> code. The code is
    judged only on site, so a far-away player cannot probe codes."""
    if member.get("last_lat") is None or member.get("last_lon") is None:
        return "no_location"
    if not is_fresh_fix(member.get("last_loc_at"), member.get("live_until"), now):
        return "stale"
    if point.get("lat") is None or point.get("lon") is None:
        return "far"
    dist = haversine_m(member["last_lat"], member["last_lon"], point["lat"], point["lon"])
    if dist > effective_radius(member.get("last_accuracy")):
        return "far"
    # Several accepted codes may be stored as "careem9|carrem9" (typos on the sign).
    accepted = {normalize_code(c) for c in (point.get("code") or "").split("|") if c.strip()}
    if normalize_code(code) not in accepted:
        return "wrong"
    return "ok"


def is_trusted_location(via_bot: bool, forwarded: bool, venue: bool, live_period: int | None, edited: bool) -> bool:
    """Whether a location may be stored and used for code checks.

    Only live locations from the player's own device count: not sent via an
    inline bot, not forwarded, not a venue, and either the first live message
    (live_period set) or an edited live tick. One-shot locations — including
    pins picked by hand on the map — can be faked from the sofa."""
    if via_bot or forwarded or venue:
        return False
    return live_period is not None or edited


def _live_until(message: Message) -> str | None:
    """UTC ISO moment the live sharing of this message ends (None if not live)."""
    period = message.location.live_period
    if period is None:
        return None
    sent = message.date if message.date.tzinfo else message.date.replace(tzinfo=timezone.utc)
    return (sent + timedelta(seconds=period)).isoformat()


# ── Team state helpers ────────────────────────────────────────────────────────


def _duration_text(team: dict) -> str:
    if not team.get("started_at") or not team.get("finished_at"):
        return "—"
    start = datetime.fromisoformat(team["started_at"])
    end = datetime.fromisoformat(team["finished_at"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return fmt_duration(int((end - start).total_seconds()))


async def _final_text(team: dict) -> str:
    hint = await db.get_setting("final_hint")
    shown = html.escape(hint) if hint else texts.FINAL_NO_HINT
    return texts.FINAL_TEXT.format(hint=shown, duration=_duration_text(team))


async def _state_text(team: dict, member: dict | None) -> str:
    """Current point (with distance) or the final hint if the route is done."""
    if team.get("finished_at") is None:
        point = await db.get_current_point(team)
        if point is not None:
            return render_target(member, point)
    return await _final_text(team)


async def _forget_live(team_id: int) -> None:
    for uid in await db.get_team_member_ids(team_id):
        _live_msg.pop(uid, None)
        _live_last_edit.pop(uid, None)


async def notify_team(bot: Bot, team_id: int, text: str, exclude: int | None = None) -> None:
    for uid in await db.get_team_member_ids(team_id):
        if uid == exclude:
            continue
        try:
            await bot.send_message(uid, text)
        except Exception as exc:  # blocked bot / flood limit — don't break delivery to others
            log.warning("notify_team: send to %s failed: %r", uid, exc)


async def _ask_password(message: Message, state: FSMContext) -> None:
    await state.set_state(PlayerLogin.waiting_password)
    await message.answer(texts.ASK_PASSWORD)


async def _member_and_team(user_id: int) -> tuple[dict | None, dict | None]:
    """Member and team of a player; any interaction (re)starts the team clock."""
    member = await db.get_member(user_id)
    if member is None:
        return None, None
    await db.ensure_started(member["team_id"], _now().isoformat())
    return member, await db.get_team(member["team_id"])


# ── Handlers ──────────────────────────────────────────────────────────────────


@player_router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    member, team = await _member_and_team(message.from_user.id)
    if member is None or team is None:
        await _ask_password(message, state)
        return
    await message.answer(
        f"{await _state_text(team, member)}\n\n{texts.LIVE_TIP}", reply_markup=location_keyboard()
    )


@player_router.message(Command("logout"))
async def on_logout(message: Message, state: FSMContext) -> None:
    await db.leave_team(message.from_user.id)
    _live_msg.pop(message.from_user.id, None)
    _live_last_edit.pop(message.from_user.id, None)
    await message.answer(texts.LEFT)
    await _ask_password(message, state)


@player_router.message(PlayerLogin.waiting_password, F.text, ~F.text.startswith("/"))
async def on_password(message: Message, state: FSMContext) -> None:
    await _try_password(message, state)


async def _try_password(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    if _throttle.is_blocked(uid):
        await message.answer(texts.TOO_MANY_ATTEMPTS)
        return
    team = await db.get_team_by_password(message.text.strip())
    if team is None:
        _throttle.record_fail(uid)
        await message.answer(texts.WRONG_PASSWORD)
        return
    _throttle.reset(uid)
    team = await db.join_team(uid, team["id"], _now().isoformat())
    await state.clear()
    member = await db.get_member(uid)
    await message.answer(
        texts.JOINED.format(team=html.escape(team["name"] or "")), reply_markup=location_keyboard()
    )
    await message.answer(f"{await _state_text(team, member)}\n\n{texts.LIVE_TIP}")


@player_router.message(F.location)
async def on_location(message: Message, state: FSMContext) -> None:
    member, team = await _member_and_team(message.from_user.id)
    if member is None or team is None:
        await _ask_password(message, state)
        return
    uid = message.from_user.id
    loc = message.location
    if message.via_bot is not None or message.forward_origin is not None or message.venue is not None:
        return  # someone else's / forwarded / venue locations are ignored outright
    if not is_trusted_location(False, False, False, loc.live_period, edited=False):
        # one-shot fix (button or map pin): show distance only, never store it for code checks
        adhoc = {**member, "last_lat": loc.latitude, "last_lon": loc.longitude, "last_accuracy": loc.horizontal_accuracy}
        await message.answer(f"{await _state_text(team, adhoc)}\n\n{texts.LIVE_NEEDED}")
        return
    # first message of a live sharing: store it and make our reply the live status message
    await db.update_member_location(
        uid, loc.latitude, loc.longitude, loc.horizontal_accuracy, _now().isoformat(), _live_until(message)
    )
    member = await db.get_member(uid)
    sent = await message.answer(await _state_text(team, member))
    if team.get("finished_at") is None:
        _live_msg[uid] = (message.chat.id, sent.message_id, team["current_position"])
        _live_last_edit[uid] = asyncio.get_running_loop().time()


@player_router.edited_message(F.location)
async def on_location_live(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    loc = message.location
    if not is_trusted_location(
        message.via_bot is not None, message.forward_origin is not None, message.venue is not None,
        loc.live_period, edited=True,
    ):
        return
    member, team = await _member_and_team(uid)
    if member is None or team is None:
        return
    await db.update_member_location(
        uid, loc.latitude, loc.longitude, loc.horizontal_accuracy, _now().isoformat(), _live_until(message)
    )
    if team.get("finished_at") is not None:
        return
    point = await db.get_current_point(team)
    if point is None:
        return
    member = await db.get_member(uid)
    await _push_live(bot, uid, message.chat.id, render_target(member, point), team["current_position"])


async def _push_live(bot: Bot, uid: int, chat_id: int, text: str, position: int) -> None:
    """Edit the player's live status message (throttled), or send a new one if
    there is none for the current point or the old one can't be edited."""
    loop = asyncio.get_running_loop()
    stored = _live_msg.get(uid)
    if stored is None or stored[2] != position:
        try:
            sent = await bot.send_message(chat_id, text)
        except TelegramAPIError as exc:
            log.warning("live status send to %s failed: %r", uid, exc)
            return
        _live_msg[uid] = (chat_id, sent.message_id, position)
        _live_last_edit[uid] = loop.time()
    elif loop.time() - _live_last_edit.get(uid, 0.0) >= LIVE_EDIT_MIN_INTERVAL_S:
        _live_last_edit[uid] = loop.time()
        try:
            await bot.edit_message_text(chat_id=stored[0], message_id=stored[1], text=text)
        except TelegramRetryAfter:
            pass  # flood control: just skip this tick
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc):
                _live_msg.pop(uid, None)  # deleted / too old: next tick sends a fresh message
        except TelegramAPIError as exc:  # blocked bot etc. — never break the update loop
            log.warning("live status edit for %s failed: %r", uid, exc)


@player_router.message(StateFilter(default_state), F.text, ~F.text.startswith("/"))
async def on_code(message: Message, bot: Bot, state: FSMContext) -> None:
    uid = message.from_user.id
    member, team = await _member_and_team(uid)
    if member is None or team is None:
        await _try_password(message, state)  # survives a restart wiping FSM storage
        return

    point = await db.get_current_point(team) if team.get("finished_at") is None else None
    if point is None:  # finished, or route shortened by admin mid-game: treat as finished
        try:
            await message.answer(await _final_text(team))
        except TelegramAPIError as exc:
            log.warning("final text to %s failed: %r", uid, exc)
        return

    now = _now()
    result = check_code(member, point, message.text, now)
    if result == "wrong":
        await message.answer(texts.CODE_WRONG)
    elif result in ("stale", "no_location"):
        await message.answer(texts.CODE_STALE if result == "stale" else texts.CODE_NO_LOCATION)
    elif result == "far":
        if member.get("last_lat") is None or point.get("lat") is None:
            await message.answer(texts.CODE_FAR_UNKNOWN)
        else:
            dist = haversine_m(member["last_lat"], member["last_lon"], point["lat"], point["lon"])
            await message.answer(texts.CODE_FAR.format(dist=fmt_dist(dist)))
    else:
        await _accept_code(message, bot, team, member, point, now)


async def _accept_code(message: Message, bot: Bot, team: dict, member: dict, point: dict, now: datetime) -> None:
    uid = message.from_user.id
    total = len(await db.get_points())
    adv = await db.advance_team(team["id"], team["current_position"], point["id"], uid, now.isoformat(), total)
    if adv is None:  # a teammate got there first
        fresh = await db.get_team(team["id"])
        await message.answer(await _state_text(fresh, member) if fresh else texts.NOT_IN_TEAM)
        return

    await _forget_live(team["id"])
    taken = texts.POINT_TAKEN.format(n=point["position"], who=html.escape(message.from_user.full_name))
    nxt = await db.get_current_point(adv) if adv.get("finished_at") is None else None
    if nxt is None:
        body = await _final_text(adv)
        await notify_team(bot, team["id"], f"{taken}\n\n{body}")
        return
    # each recipient sees the distance from their own last fix
    for member_id in await db.get_team_member_ids(team["id"]):
        try:
            text = f"{taken}\n\n{render_target(await db.get_member(member_id), nxt)}"
            await bot.send_message(member_id, text)
        except Exception as exc:
            log.warning("next-point send to %s failed: %r", member_id, exc)
