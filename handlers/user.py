from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

import db
from config import ACTIVATION_RADIUS_M
from keyboards import activate_keyboard, location_keyboard, refresh_keyboard
from utils.geo import haversine_m
from utils.timer import (
    cancel_cooldown_display,
    is_refresh_locked,
    start_cooldown_display,
    start_refresh_timer,
)

user_router = Router()


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


def _build_distances(
    user_lat: float,
    user_lon: float,
    points: list[dict],
    activated_ids: list[int],
) -> tuple[str, list[int]]:
    """Return (formatted text, list of nearby unclaimed point IDs)."""
    lines: list[str] = []
    nearby: list[int] = []

    for p in points:
        done_mark = " ✔️" if p["id"] in activated_ids else ""
        if p["lat"] is None:
            lines.append(f"📍 {p['label']} — не настроена{done_mark}")
            continue

        dist = haversine_m(user_lat, user_lon, p["lat"], p["lon"])

        if dist <= ACTIVATION_RADIUS_M and p["id"] not in activated_ids:
            lines.append(f"🎯 {p['label']} — {_fmt_dist(dist)}{done_mark}")
            nearby.append(p["id"])
        elif dist <= ACTIVATION_RADIUS_M * 5:
            lines.append(f"🔥 {p['label']} — {_fmt_dist(dist)}{done_mark}")
        else:
            lines.append(f"📍 {p['label']} — {_fmt_dist(dist)}{done_mark}")

    return "\n".join(lines), nearby


# ── /start ────────────────────────────────────────────────────────────────────

@user_router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user      = await db.get_or_create_user(message.from_user.id)
    remaining = _remaining_seconds(user["cooldown_until"])

    if remaining > 0:
        await message.answer(
            f"⏳ Вы можете активировать следующую точку через:\n"
            f"<b>{_fmt_time(remaining)}</b>\n\n"
            f"Ожидайте или обратитесь к администратору."
        )
        return

    await message.answer(
        "👋 Добро пожаловать в квест!\n\n"
        "Поделитесь своей геолокацией, чтобы увидеть расстояния до точек.",
        reply_markup=location_keyboard(),
    )


# ── Location ──────────────────────────────────────────────────────────────────

@user_router.message(F.location)
async def on_location(message: Message, bot: Bot) -> None:
    user_id   = message.from_user.id
    user      = await db.get_or_create_user(user_id)
    remaining = _remaining_seconds(user["cooldown_until"])

    if remaining > 0:
        await message.answer(
            f"⏳ Кулдаун активен. Следующая активация через "
            f"<b>{_fmt_time(remaining)}</b>"
        )
        return

    lat = message.location.latitude
    lon = message.location.longitude
    await db.update_user_location(user_id, lat, lon)

    points    = await db.get_points()
    activated = await db.get_user_activated_points(user_id)
    text, nearby = _build_distances(lat, lon, points, activated)

    await message.answer(text, reply_markup=refresh_keyboard())

    if nearby:
        point = next(p for p in points if p["id"] == nearby[0])
        await message.answer(
            f"🎯 Вы у <b>{point['label']}</b>!\n\nХотите активировать?",
            reply_markup=activate_keyboard(nearby[0]),
        )


# ── Refresh button ────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "user:refresh")
async def cb_refresh(callback: CallbackQuery, bot: Bot) -> None:
    user_id = callback.from_user.id

    if is_refresh_locked(user_id):
        await callback.answer("⏳ Подождите...", show_alert=False)
        return

    user      = await db.get_or_create_user(user_id)
    remaining = _remaining_seconds(user["cooldown_until"])
    if remaining > 0:
        await callback.answer(
            f"⏳ Кулдаун: {_fmt_time(remaining)}", show_alert=True
        )
        return

    if not user["last_lat"]:
        await callback.answer("Сначала отправьте геолокацию.", show_alert=True)
        return

    refresh_sec = int(await db.get_setting("refresh_delay_sec"))
    points      = await db.get_points()
    activated   = await db.get_user_activated_points(user_id)
    text, nearby = _build_distances(user["last_lat"], user["last_lon"], points, activated)

    msg = callback.message

    async def on_tick(sec: int) -> None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                reply_markup=refresh_keyboard(f"⏳ {sec}с"),
            )
        except Exception:
            pass

    async def on_done() -> None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                reply_markup=refresh_keyboard("🔄 Обновить"),
            )
        except Exception:
            pass

    await callback.message.edit_text(
        text, reply_markup=refresh_keyboard(f"⏳ {refresh_sec}с")
    )
    start_refresh_timer(user_id, refresh_sec, on_tick, on_done)
    await callback.answer()

    if nearby:
        point = next(p for p in points if p["id"] == nearby[0])
        await callback.message.answer(
            f"🎯 Вы у <b>{point['label']}</b>!\n\nХотите активировать?",
            reply_markup=activate_keyboard(nearby[0]),
        )


# ── Activation ────────────────────────────────────────────────────────────────

@user_router.callback_query(F.data == "user:activate:no")
async def cb_activate_no(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Хорошо! Продолжайте исследование. 🗺")
    await callback.answer()


@user_router.callback_query(F.data.startswith("user:activate:"))
async def cb_activate(callback: CallbackQuery, bot: Bot) -> None:
    user_id  = callback.from_user.id
    point_id = int(callback.data.split(":")[2])

    user      = await db.get_or_create_user(user_id)
    remaining = _remaining_seconds(user["cooldown_until"])
    if remaining > 0:
        await callback.answer(
            f"⏳ Кулдаун активен: {_fmt_time(remaining)}", show_alert=True
        )
        return

    activated = await db.get_user_activated_points(user_id)
    if point_id in activated:
        await callback.answer("Вы уже активировали эту точку!", show_alert=True)
        return

    # Guard: re-verify distance from last known location
    point = await db.get_point(point_id)
    if not point:
        await callback.answer("Точка не найдена.", show_alert=True)
        return

    if user["last_lat"] and point["lat"] is not None:
        dist = haversine_m(user["last_lat"], user["last_lon"], point["lat"], point["lon"])
        if dist > ACTIVATION_RADIUS_M * 4:
            await callback.answer(
                "Вы слишком далеко от точки. Подойдите ближе.", show_alert=True
            )
            return

    await callback.answer()
    await callback.message.edit_reply_markup()  # remove activation buttons

    # Send photo fragment
    if point["photo_file_id"]:
        await bot.send_photo(
            chat_id=callback.message.chat.id,
            photo=point["photo_file_id"],
            caption=f"🏆 Фрагмент <b>{point['label']}</b> получен!",
        )
    else:
        await callback.message.answer(
            f"🏆 Вы активировали <b>{point['label']}</b>!\n"
            "(фото ещё не загружено администратором)"
        )

    # Record activation and set cooldown
    await db.record_activation(user_id, point_id)
    cooldown_min  = int(await db.get_setting("activation_cooldown_min"))
    cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_min)
    await db.set_user_cooldown(user_id, cooldown_until.isoformat())

    total_sec = cooldown_min * 60
    cd_msg = await bot.send_message(
        chat_id=callback.message.chat.id,
        text=(
            f"⏳ Вы можете активировать следующую точку через:\n"
            f"<b>{_fmt_time(total_sec)}</b>"
        ),
    )

    # Cancel any stale cooldown display for this user
    cancel_cooldown_display(user_id)

    async def on_tick(sec: int) -> None:
        try:
            await bot.edit_message_text(
                chat_id=cd_msg.chat.id,
                message_id=cd_msg.message_id,
                text=(
                    f"⏳ Вы можете активировать следующую точку через:\n"
                    f"<b>{_fmt_time(sec)}</b>"
                ),
            )
        except Exception:
            pass

    async def on_done() -> None:
        try:
            await bot.edit_message_text(
                chat_id=cd_msg.chat.id,
                message_id=cd_msg.message_id,
                text=(
                    "✅ Кулдаун снят!\n\n"
                    "Поделитесь геолокацией, чтобы продолжить поиск."
                ),
            )
        except Exception:
            pass
        await db.reset_user_cooldown(user_id)

    start_cooldown_display(user_id, total_sec, on_tick, on_done)
