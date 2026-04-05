import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import db
from config import ADMINS
from keyboards import (
    admin_main_menu,
    admin_player_actions,
    admin_players_menu,
    admin_point_actions,
    admin_points_menu,
    admin_settings_menu,
    language_select_keyboard,
    location_keyboard,
)
from states import AdminPoint, AdminSettings

admin_router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ── /myid — anyone can check their Telegram ID ───────────────────────────────

@admin_router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


# ── /cancel — admin can always reset stuck FSM state ─────────────────────────

@admin_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("❌ Действие отменено. Введи /admin чтобы вернуться в меню.")
    else:
        await message.answer("Нечего отменять. Введи /admin для открытия меню.")


# ── /admin entry point ────────────────────────────────────────────────────────

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(
            f"⛔️ Нет доступа.\n"
            f"Ваш ID: <code>{message.from_user.id}</code>\n\n"
            f"Попросите владельца добавить ваш ID в ADMIN_IDS."
        )
        return
    await state.clear()
    await message.answer("🔑 Панель администратора", reply_markup=admin_main_menu())


# ── Main menu callback ────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("🔑 Панель администратора", reply_markup=admin_main_menu())
    await callback.answer()


# ── Play as user ──────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:play_as_user")
async def cb_play_as_user(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    # Reset language so the selection screen appears fresh
    await db.reset_user_lang(callback.from_user.id)
    await callback.message.edit_text("🎮 Режим игрока активирован!")
    await callback.message.answer(
        "🌐 Выберите язык / Изберете език:",
        reply_markup=language_select_keyboard(),
    )
    await callback.answer()


# ── Points ────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:points")
async def cb_admin_points(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    points = await db.get_points()
    await callback.message.edit_text("⚙️ Точки квеста:", reply_markup=admin_points_menu(points))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:point:"))
async def cb_admin_point_detail(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    point_id = int(callback.data.split(":")[2])
    point = await db.get_point(point_id)
    if not point:
        await callback.answer("Точка не найдена", show_alert=True)
        return

    coords = (
        f"<code>{point['lat']}, {point['lon']}</code>"
        if point["lat"] is not None
        else "не задано"
    )
    photo = "✅ загружено" if point["photo_file_id"] else "❌ не загружено"
    text = (
        f"<b>{point['label']}</b>\n\n"
        f"📍 Координаты: {coords}\n"
        f"🖼 Фото: {photo}"
    )
    await callback.message.edit_text(text, reply_markup=admin_point_actions(point_id))
    await callback.answer()


# Coords flow

@admin_router.callback_query(F.data.startswith("admin:coords:"))
async def cb_admin_set_coords(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    point_id = int(callback.data.split(":")[2])
    await state.update_data(point_id=point_id)
    await state.set_state(AdminPoint.waiting_coords)
    await callback.message.edit_text(
        f"📍 Введи координаты для <b>Точки {point_id}</b>:\n\n"
        "Формат: <code>55.751244 37.618423</code>\n"
        "Или скопируй из Google Maps: <code>55.751244, 37.618423</code>\n\n"
        "/cancel — отменить"
    )
    await callback.answer()


@admin_router.message(AdminPoint.waiting_coords)
async def msg_admin_coords(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    point_id: int = data["point_id"]

    try:
        # Support formats: "55.1 37.2", "55.1, 37.2", "55,1 37,2" (comma as decimal)
        parts = [p for p in re.split(r"[\s,;]+", message.text.strip()) if p]
        if len(parts) < 2:
            raise ValueError
        # Replace comma-as-decimal-separator but only within each part
        lat = float(parts[0].replace(",", "."))
        lon = float(parts[1].replace(",", "."))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат.\n"
            "Примеры:\n"
            "<code>55.751244 37.618423</code>\n"
            "<code>55.751244, 37.618423</code>"
        )
        return

    await db.update_point_coords(point_id, lat, lon)
    await state.set_state(AdminPoint.waiting_photo)
    await message.answer(
        f"✅ Координаты Точки {point_id} сохранены: <code>{lat}, {lon}</code>\n\n"
        "Теперь отправь фото для этой точки:"
    )


# Photo flow

@admin_router.callback_query(F.data.startswith("admin:photo:"))
async def cb_admin_set_photo(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    point_id = int(callback.data.split(":")[2])
    await state.update_data(point_id=point_id)
    await state.set_state(AdminPoint.waiting_photo)
    await callback.message.edit_text(f"🖼 Отправь фото для <b>Точки {point_id}</b>:\n\n/cancel — отменить")
    await callback.answer()


@admin_router.message(AdminPoint.waiting_photo, F.photo)
async def msg_admin_photo(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    point_id: int = data["point_id"]

    file_id = message.photo[-1].file_id
    await db.update_point_photo(point_id, file_id)
    await state.clear()

    await message.answer(f"✅ Фото для Точки {point_id} сохранено!")

    # Auto-advance: find next unconfigured point and start its setup
    points = await db.get_points()
    next_point = next(
        (p for p in points if p["id"] > point_id and (p["lat"] is None or not p["photo_file_id"])),
        None,
    )
    if next_point:
        await state.update_data(point_id=next_point["id"])
        await state.set_state(AdminPoint.waiting_coords)
        missing = []
        if next_point["lat"] is None:
            missing.append("координаты")
        if not next_point["photo_file_id"]:
            missing.append("фото")
        await message.answer(
            f"➡️ <b>{next_point['label']}</b> ещё не настроена ({', '.join(missing)}).\n\n"
            f"📍 Введи координаты:\n"
            f"Пример: <code>55.751244 37.618423</code>\n\n"
            f"/cancel — пропустить и выйти в меню"
        )
    else:
        await message.answer(
            "🎉 Все точки настроены!",
            reply_markup=admin_points_menu(points),
        )


@admin_router.message(AdminPoint.waiting_photo)
async def msg_admin_photo_wrong(message: Message) -> None:
    await message.answer("❌ Нужно отправить именно фото (не файл, не стикер).")


# ── Players ───────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:players")
async def cb_admin_players(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    users = await db.get_all_users()
    if not users:
        await callback.message.edit_text(
            "👥 Нет зарегистрированных игроков.", reply_markup=admin_main_menu()
        )
        await callback.answer()
        return
    await callback.message.edit_text("👥 Игроки:", reply_markup=admin_players_menu(users))
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:player:"))
async def cb_admin_player_detail(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    user_id = int(callback.data.split(":")[2])
    users = await db.get_all_users()
    user = next((u for u in users if u["user_id"] == user_id), None)
    if not user:
        await callback.answer("Игрок не найден", show_alert=True)
        return

    cd = f"⏳ до {user['cooldown_until']}" if user["cooldown_until"] else "нет"
    text = (
        f"👤 ID: <code>{user_id}</code>\n"
        f"⏱ Кулдаун: {cd}\n"
        f"🏆 Закрыто точек: {user['points_count']}"
    )
    await callback.message.edit_text(
        text, reply_markup=admin_player_actions(user_id, bool(user["cooldown_until"]))
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin:reset_cd:"))
async def cb_admin_reset_cd(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    user_id = int(callback.data.split(":")[2])
    await db.reset_user_cooldown(user_id)
    await callback.answer("✅ Кулдаун сброшен")

    users = await db.get_all_users()
    user  = next((u for u in users if u["user_id"] == user_id), None)
    if user:
        text = (
            f"👤 ID: <code>{user_id}</code>\n"
            f"⏱ Кулдаун: нет\n"
            f"🏆 Закрыто точек: {user['points_count']}"
        )
        await callback.message.edit_text(
            text, reply_markup=admin_player_actions(user_id, False)
        )


@admin_router.callback_query(F.data.startswith("admin:reset_all:"))
async def cb_admin_reset_all(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    user_id = int(callback.data.split(":")[2])
    await db.reset_user_progress(user_id)
    await callback.answer("✅ Прогресс игрока полностью сброшен")

    users = await db.get_all_users()
    await callback.message.edit_text("👥 Игроки:", reply_markup=admin_players_menu(users))


# ── Settings ──────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:settings")
async def cb_admin_settings(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    refresh_sec  = await db.get_setting("refresh_delay_sec")
    cooldown_min = await db.get_setting("activation_cooldown_min")
    await callback.message.edit_text(
        "🔧 Настройки бота:",
        reply_markup=admin_settings_menu(refresh_sec, cooldown_min),
    )
    await callback.answer()


_SETTING_LABELS = {
    "refresh_delay_sec":       "задержку кнопки Обновить (секунды, целое > 0)",
    "activation_cooldown_min": "кулдаун после активации (минуты, целое > 0)",
}


@admin_router.callback_query(F.data.startswith("admin:set:"))
async def cb_admin_set_setting(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    key = callback.data.split(":", 2)[2]
    await state.update_data(setting_key=key)
    await state.set_state(AdminSettings.waiting_value)
    label = _SETTING_LABELS.get(key, key)
    await callback.message.edit_text(f"✏️ Введи новое значение для:\n<b>{label}</b>\n\n/cancel — отменить")
    await callback.answer()


@admin_router.message(AdminSettings.waiting_value)
async def msg_admin_setting_value(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    key: str = data["setting_key"]

    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое положительное число.")
        return

    await db.set_setting(key, str(val))
    await state.clear()

    refresh_sec  = await db.get_setting("refresh_delay_sec")
    cooldown_min = await db.get_setting("activation_cooldown_min")
    await message.answer(
        "✅ Настройка сохранена!",
        reply_markup=admin_settings_menu(refresh_sec, cooldown_min),
    )


# ── Fallback: admin sends text when bot isn't waiting for input ───────────────

@admin_router.message(F.text, ~F.text.startswith("/"))
async def admin_text_fallback(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    current = await state.get_state()
    if current is not None:
        return  # let other handlers deal with active states
    await message.answer(
        "ℹ️ Бот сейчас ничего не ждёт.\n\n"
        "Используй /admin чтобы открыть меню,\n"
        "или /cancel чтобы сбросить состояние."
    )
