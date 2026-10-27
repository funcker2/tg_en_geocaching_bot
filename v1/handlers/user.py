import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message

import db
from config import (
    ACCURACY_BONUS_CAP_M,
    ACTIVATION_RADIUS_M,
    LIVE_EDIT_MIN_INTERVAL_S,
    LOCATION_STALE_S,
    POOR_ACCURACY_THRESHOLD_M,
)
from i18n import t
from keyboards import (
    activate_keyboard,
    language_select_keyboard,
    location_keyboard,
)
from utils.geo import fuse_fix, haversine_m
from utils.timer import (
    cancel_cooldown_display,
    start_cooldown_display,
)

user_router = Router()

# Per-user live-location session state (in-process, not persisted — a restart
# simply means the next live-location edit re-creates the status message).
# live_msg:          (chat_id, message_id) of the status message being edited in place
# last_edit_monotonic: loop.time() of the last successful edit, for throttling
# prompted:          point ids currently shown with an "activate?" prompt, so we
#                     don't resend it on every ~5-20s live-location tick while
#                     the player is just standing near the point
_live_msg: dict[int, tuple[int, int]] = {}
_live_last_edit: dict[int, float] = {}
_live_prompted: dict[int, set[int]] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_dist(metres: float) -> str:
    return f"{int(metres)} м" if metres < 1000 else f"{metres / 1000:.1f} км"


def _fmt_time(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    return f"{m}:{s:02d}"


def _remaining_seconds(cooldown_until: str | None) -> int:
    if not cooldown_until:
        return 0
    try:
        until = datetime.fromisoformat(cooldown_until).replace(tzinfo=timezone.utc)
        delta = (until - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(delta))
    except Exception:
        return 0


def _age_seconds(loc_at_iso: str | None) -> float | None:
    if not loc_at_iso:
        return None
    try:
        at = datetime.fromisoformat(loc_at_iso).replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - at).total_seconds())
    except Exception:
        return None


def _effective_radius(accuracy: float | None) -> float:
    """
    Activation radius, generously widened while the GPS fix is still
    imprecise. Capped so a very poor fix can't be used to fake proximity to
    a point that's genuinely far away.
    """
    if not accuracy or accuracy <= 0:
        return ACTIVATION_RADIUS_M
    return ACTIVATION_RADIUS_M + min(accuracy, ACCURACY_BONUS_CAP_M)


async def _ingest_fix(
    user_id: int,
    prev_user: dict,
    lat: float,
    lon: float,
    accuracy: float | None,
    allow_fuse: bool = True,
) -> tuple[float, float, float | None]:
    """
    Optionally fuse the new raw fix with the last known one (if fresh), then
    persist it. Returns the (possibly smoothed) lat/lon to use for this
    update, plus the raw accuracy actually reported for this fix (used for
    hints/effective radius).

    allow_fuse=False for the live-location stream: consecutive ticks there
    are genuinely different positions of a moving player, not repeated noisy
    reads of one spot, so smoothing them would just lag behind real movement.
    """
    if allow_fuse:
        prev_age = _age_seconds(prev_user.get("last_loc_at"))
        lat, lon = fuse_fix(
            prev_user.get("last_lat"),
            prev_user.get("last_lon"),
            prev_user.get("last_accuracy"),
            prev_age,
            lat,
            lon,
            accuracy,
        )
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.update_user_location(user_id, lat, lon, accuracy, now_iso)
    return lat, lon, accuracy


def _build_distances(
    user_lat: float,
    user_lon: float,
    points: list[dict],
    activated_ids: list[int],
    lang: str,
    accuracy: float | None = None,
) -> tuple[str, list[int]]:
    """Return (formatted distances text, list of nearby unclaimed point IDs)."""
    lines: list[str] = []
    nearby: list[int] = []
    radius = _effective_radius(accuracy)

    for p in points:
        done_mark = " ✔️" if p["id"] in activated_ids else ""
        if p["lat"] is None:
            lines.append(f"📍 {p['label']} — {t(lang, 'point_not_configured')}{done_mark}")
            continue

        dist = haversine_m(user_lat, user_lon, p["lat"], p["lon"])

        if dist <= radius and p["id"] not in activated_ids:
            lines.append(f"🎯 {p['label']} — {_fmt_dist(dist)}{done_mark}")
            nearby.append(p["id"])
        elif dist <= ACTIVATION_RADIUS_M * 5:
            lines.append(f"🔥 {p['label']} — {_fmt_dist(dist)}{done_mark}")
        else:
            lines.append(f"📍 {p['label']} — {_fmt_dist(dist)}{done_mark}")

    if accuracy and accuracy > POOR_ACCURACY_THRESHOLD_M:
        lines.append("")
        lines.append(t(lang, "accuracy_poor_hint", acc=int(accuracy)))
    elif accuracy:
        lines.append("")
        lines.append(t(lang, "accuracy_footer", acc=int(accuracy)))

    return "\n".join(lines), nearby


# ── Language selection ────────────────────────────────────────────────────────

@user_router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = await db.get_or_create_user(message.from_user.id)
    lang = user["lang"] or "ru"

    if not user["lang"]:
        await db.set_user_lang(message.from_user.id, "ru")

    remaining = _remaining_seconds(user["cooldown_until"])
    if remaining > 0:
        await message.answer(t(lang, "cooldown_gate", time=_fmt_time(remaining)))
        return

    await message.answer(t(lang, "welcome"), reply_markup=location_keyboard(lang))


@user_router.message(Command("lang"))
async def cmd_lang(message: Message) -> None:
    """Allow any user to change language at any time."""
    await message.answer(
        "🌐 Выберите язык / Изберете език:",
        reply_markup=language_select_keyboard(),
    )


@user_router.callback_query(F.data == "user:change_lang")
async def cb_change_lang(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "🌐 Выберите язык / Изберете език:",
        reply_markup=language_select_keyboard(),
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("user:lang:"))
async def cb_set_lang(callback: CallbackQuery) -> None:
    lang = callback.data.split(":")[2]
    if lang not in ("ru", "bg"):
        await callback.answer()
        return

    user_id = callback.from_user.id
    await db.get_or_create_user(user_id)
    await db.set_user_lang(user_id, lang)

    await callback.message.edit_text(t(lang, "lang_set"))
    await callback.answer()

    user = await db.get_or_create_user(user_id)
    remaining = _remaining_seconds(user["cooldown_until"])
    if remaining > 0:
        await callback.message.answer(t(lang, "cooldown_gate", time=_fmt_time(remaining)))
        return

    await callback.message.answer(t(lang, "welcome"), reply_markup=location_keyboard(lang))


# ── Location ──────────────────────────────────────────────────────────────────

@user_router.message(F.location)
async def on_location(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    user    = await db.get_or_create_user(user_id)
    lang    = user["lang"] or "ru"

    remaining = _remaining_seconds(user["cooldown_until"])
    if remaining > 0:
        await message.answer(t(lang, "cooldown_still", time=_fmt_time(remaining)))
        return

    is_first_fix = user.get("last_loc_at") is None
    is_live       = message.location.live_period is not None

    lat, lon, accuracy = await _ingest_fix(
        user_id, user,
        message.location.latitude,
        message.location.longitude,
        message.location.horizontal_accuracy,
    )

    points    = await db.get_points()
    activated = await db.get_user_activated_points(user_id)
    text, nearby = _build_distances(lat, lon, points, activated, lang, accuracy)

    await message.answer(text)

    if nearby:
        point = next(p for p in points if p["id"] == nearby[0])
        await message.answer(
            t(lang, "at_point_prompt", label=point["label"]),
            reply_markup=activate_keyboard(nearby[0], lang),
        )
        _live_prompted.setdefault(user_id, set()).add(nearby[0])

    if is_first_fix and not is_live:
        await message.answer(t(lang, "live_location_tip"))


@user_router.edited_message(F.location)
async def on_location_edited(message: Message, bot: Bot) -> None:
    """
    Handle continuous updates from Telegram's "Share Live Location". These
    arrive every ~5-20s while the player is moving, without any extra tap —
    this is what actually removes the "wait and re-send" delay from the
    old one-shot flow. The distances message is edited in place (throttled)
    instead of spamming a new message per tick; the activation prompt is
    only (re-)sent when a point transitions into range.
    """
    user_id = message.from_user.id
    user    = await db.get_or_create_user(user_id)
    lang    = user["lang"] or "ru"

    if _remaining_seconds(user["cooldown_until"]) > 0:
        return

    lat, lon, accuracy = await _ingest_fix(
        user_id, user,
        message.location.latitude,
        message.location.longitude,
        message.location.horizontal_accuracy,
        allow_fuse=False,
    )

    points    = await db.get_points()
    activated = await db.get_user_activated_points(user_id)
    text, nearby = _build_distances(lat, lon, points, activated, lang, accuracy)
    nearby_set = set(nearby)

    loop = asyncio.get_event_loop()
    last_edit = _live_last_edit.get(user_id, 0.0)
    chat_id, msg_id = _live_msg.get(user_id, (message.chat.id, None))

    if msg_id is None:
        sent = await bot.send_message(chat_id=message.chat.id, text=text)
        _live_msg[user_id] = (message.chat.id, sent.message_id)
        _live_last_edit[user_id] = loop.time()
    elif loop.time() - last_edit >= LIVE_EDIT_MIN_INTERVAL_S:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except Exception:
            pass
        _live_last_edit[user_id] = loop.time()

    prompted = _live_prompted.setdefault(user_id, set())
    newly_nearby = nearby_set - prompted
    if newly_nearby:
        point_id = next(iter(newly_nearby))
        point = next(p for p in points if p["id"] == point_id)
        await message.answer(
            t(lang, "at_point_prompt", label=point["label"]),
            reply_markup=activate_keyboard(point_id, lang),
        )
    _live_prompted[user_id] = set(nearby_set)


# ── Activation ────────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "user:activate:no")
async def cb_activate_no(callback: CallbackQuery) -> None:
    user  = await db.get_or_create_user(callback.from_user.id)
    lang  = user["lang"] or "ru"
    await callback.message.edit_text(t(lang, "activate_declined"))
    await callback.answer()


@user_router.callback_query(F.data.startswith("user:activate:"))
async def cb_activate(callback: CallbackQuery, bot: Bot) -> None:
    user_id  = callback.from_user.id
    point_id = int(callback.data.split(":")[2])

    user      = await db.get_or_create_user(user_id)
    lang      = user["lang"] or "ru"
    remaining = _remaining_seconds(user["cooldown_until"])

    if remaining > 0:
        await callback.answer(t(lang, "cooldown_active", time=_fmt_time(remaining)), show_alert=True)
        return

    activated = await db.get_user_activated_points(user_id)
    if point_id in activated:
        await callback.answer(t(lang, "already_activated"), show_alert=True)
        return

    point = await db.get_point(point_id)
    if not point:
        await callback.answer("—", show_alert=True)
        return

    if user["last_lat"] and point["lat"] is not None:
        age = _age_seconds(user.get("last_loc_at"))
        if age is not None and age > LOCATION_STALE_S:
            await callback.answer(t(lang, "location_stale"), show_alert=True)
            return

        dist = haversine_m(user["last_lat"], user["last_lon"], point["lat"], point["lon"])
        if dist > _effective_radius(user.get("last_accuracy")) * 4:
            await callback.answer(t(lang, "too_far"), show_alert=True)
            return

    await callback.answer()
    await callback.message.edit_reply_markup()

    if point["photo_file_id"]:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=point["photo_file_id"],
            caption=t(lang, "photo_caption", label=point["label"]),
        )
    else:
        await callback.message.answer(t(lang, "no_photo", label=point["label"]))

    await db.record_activation(user_id, point_id)
    cooldown_min   = int(await db.get_setting("activation_cooldown_min"))
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_min)
    await db.set_user_cooldown(user_id, cooldown_until.isoformat())

    total_sec = cooldown_min * 60
    cd_msg = await bot.send_message(
        chat_id=callback.message.chat.id,
        text=t(lang, "cooldown_msg", time=_fmt_time(total_sec)),
    )

    cancel_cooldown_display(user_id)

    async def on_tick(sec: int) -> None:
        try:
            await bot.edit_message_text(
                chat_id=cd_msg.chat.id,
                message_id=cd_msg.message_id,
                text=t(lang, "cooldown_msg", time=_fmt_time(sec)),
            )
        except Exception:
            pass

    async def on_done() -> None:
        try:
            await bot.edit_message_text(
                chat_id=cd_msg.chat.id,
                message_id=cd_msg.message_id,
                text=t(lang, "cooldown_done"),
            )
        except Exception:
            pass
        await db.reset_user_cooldown(user_id)

    start_cooldown_display(user_id, total_sec, on_tick, on_done)
