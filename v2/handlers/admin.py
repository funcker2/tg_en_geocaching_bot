import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import db
from admin_logic import MAX_TEAMS_AT_ONCE, format_breakdown, format_results, parse_coords, parse_count
from config import ADMINS, TZ
from handlers.player import render_target
from keyboards import (
    admin_back,
    admin_confirm,
    admin_hint_menu,
    admin_main_menu,
    admin_point_actions,
    admin_points_menu,
    admin_reset_menu,
    admin_team_actions,
    admin_teams_menu,
)
from states import AdminEdit, AdminHint, AdminPoint, AdminTeams

log = logging.getLogger(__name__)

admin_router = Router()

MENU_TITLE = "🔑 Панель администратора"
GAME_RUNNING_WARNING = "⚠️ Игра уже идёт: изменения маршрута затронут команды в пути."
CANCEL_HINT = "\n\n/cancel — отменить"
COORDS_HELP = (
    "Отправьте геопин (📎 → Геопозиция) или напишите текстом: "
    "<code>55.751244, 37.618423</code>"
)


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def _admin_event(event: Message | CallbackQuery) -> bool:
    return event.from_user is not None and is_admin(event.from_user.id)


def _text_msg(message: Message) -> bool:
    """Plain (non-command) text; commands fall through to their own handlers."""
    return bool(message.text) and not message.text.startswith("/")


async def _show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:  # e.g. "message is not modified"
        log.debug("edit_text skipped: %s", exc)
    await callback.answer()


async def _game_running() -> bool:
    return any(team["started_at"] and not team["is_test"] for team in await db.list_teams())


async def _warn_suffix() -> str:
    return f"\n\n{GAME_RUNNING_WARNING}" if await _game_running() else ""


def _tail_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[1])


# ── /myid, /cancel, /admin ────────────────────────────────────────────────────

@admin_router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@admin_router.message(Command("cancel"), _admin_event)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current:
        await message.answer("❌ Действие отменено. /admin — вернуться в меню.")
    else:
        await message.answer("Нечего отменять. /admin — открыть меню.")


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(
            f"⛔️ Нет доступа.\nВаш ID: <code>{message.from_user.id}</code>\n\n"
            "Попросите владельца добавить ваш ID в ADMIN_IDS."
        )
        return
    await state.clear()
    await message.answer(MENU_TITLE, reply_markup=admin_main_menu())


@admin_router.callback_query(F.data == "admin:main", _admin_event)
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show(callback, MENU_TITLE, admin_main_menu())


# ── Points: list and card ─────────────────────────────────────────────────────

def _point_card(point: dict) -> str:
    coords = (
        f"<code>{point['lat']}, {point['lon']}</code>"
        if point.get("lat") is not None and point.get("lon") is not None
        else "не задано"
    )
    code = f"<code>{html.escape(point['code'])}</code>" if point.get("code") else "не задан"
    return (
        f"<b>{point['position']}. {html.escape(point.get('label') or 'без названия')}</b>\n\n"
        f"📍 Координаты: {coords}\n🔑 Код: {code}"
    )


async def _show_points(callback: CallbackQuery, prefix: str = "") -> None:
    points = await db.get_points()
    await _show(callback, f"{prefix}📍 Точки маршрута:", admin_points_menu(points))


async def _show_point(callback: CallbackQuery, point_id: int, prefix: str = "") -> None:
    point = await db.get_point(point_id)
    if not point:
        await callback.answer("Точка не найдена", show_alert=True)
        return
    await _show(callback, prefix + _point_card(point), admin_point_actions(point_id))


@admin_router.callback_query(F.data == "admin:points", _admin_event)
async def cb_points(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show_points(callback)


@admin_router.callback_query(F.data.startswith("admin:pt:"), _admin_event)
async def cb_point(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show_point(callback, _tail_id(callback))


@admin_router.callback_query(F.data.startswith("admin:prev:"), _admin_event)
async def cb_preview(callback: CallbackQuery) -> None:
    point_id = _tail_id(callback)
    point = await db.get_point(point_id)
    if not point:
        await callback.answer("Точка не найдена", show_alert=True)
        return
    code = f"<code>{html.escape(point['code'])}</code>" if point.get("code") else "не задан"
    text = (
        "👁 Так точку видит игрок:\n\n"
        f"{render_target(None, point)}\n\n"
        f"Для админа: название «{html.escape(point.get('label') or '')}», код {code}"
    )
    await _show(callback, text, admin_back(f"admin:pt:{point_id}"))


@admin_router.callback_query(F.data.regexp(r"^admin:(up|down):\d+$"), _admin_event)
async def cb_move(callback: CallbackQuery) -> None:
    direction = callback.data.split(":")[1]
    point_id = _tail_id(callback)
    await db.move_point(point_id, -1 if direction == "up" else 1)
    warning = await _warn_suffix()
    await _show_point(callback, point_id, prefix=f"{warning.lstrip()}\n\n" if warning else "")


# ── Points: delete ────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data.startswith("admin:ptdel:"), _admin_event)
async def cb_point_delete(callback: CallbackQuery) -> None:
    point_id = _tail_id(callback)
    point = await db.get_point(point_id)
    if not point:
        await callback.answer("Точка не найдена", show_alert=True)
        return
    await _show(
        callback,
        f"🗑 Удалить точку «{html.escape(point.get('label') or '')}»?",
        admin_confirm(f"admin:ptdelok:{point_id}", f"admin:pt:{point_id}", "✅ Да, удалить"),
    )


@admin_router.callback_query(F.data.startswith("admin:ptdelok:"), _admin_event)
async def cb_point_delete_ok(callback: CallbackQuery) -> None:
    await db.delete_point(_tail_id(callback))
    await _show_points(callback, prefix=f"✅ Точка удалена.{await _warn_suffix()}\n\n")


# ── Points: add flow (label -> coords -> code) ────────────────────────────────

@admin_router.callback_query(F.data == "admin:ptadd", _admin_event)
async def cb_point_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminPoint.label)
    await _show(callback, "➕ Введите название новой точки." + CANCEL_HINT)


@admin_router.message(AdminPoint.label, _admin_event, _text_msg)
async def msg_add_label(message: Message, state: FSMContext) -> None:
    label = message.text.strip()
    if not label:
        await message.answer("❌ Название не может быть пустым.")
        return
    await state.update_data(label=label)
    await state.set_state(AdminPoint.coords)
    await message.answer(f"📍 Координаты точки «{html.escape(label)}».\n{COORDS_HELP}{CANCEL_HINT}")


async def _add_coords(message: Message, state: FSMContext, lat: float, lon: float) -> None:
    await state.update_data(lat=lat, lon=lon)
    await state.set_state(AdminPoint.code)
    await message.answer(
        f"✅ Координаты: <code>{lat}, {lon}</code>\n\n🔑 Введите код точки (его найдут на месте)." + CANCEL_HINT
    )


@admin_router.message(AdminPoint.coords, F.location, _admin_event)
async def msg_add_coords_geo(message: Message, state: FSMContext) -> None:
    await _add_coords(message, state, message.location.latitude, message.location.longitude)


@admin_router.message(AdminPoint.coords, _admin_event, _text_msg)
async def msg_add_coords_text(message: Message, state: FSMContext) -> None:
    parsed = parse_coords(message.text)
    if parsed is None:
        await message.answer(f"❌ Неверный формат.\n{COORDS_HELP}")
        return
    await _add_coords(message, state, *parsed)


@admin_router.message(AdminPoint.code, _admin_event, _text_msg)
async def msg_add_code(message: Message, state: FSMContext) -> None:
    code = message.text.strip()
    if not code:
        await message.answer("❌ Код не может быть пустым.")
        return
    data = await state.get_data()
    await db.add_point(data["label"], data["lat"], data["lon"], code)
    await state.clear()
    await message.answer(
        f"✅ Точка «{html.escape(data['label'])}» добавлена в конец маршрута.",
        reply_markup=admin_points_menu(await db.get_points()),
    )


# ── Points: edit flow (label / coords / code) ─────────────────────────────────

_EDIT_PROMPTS = {
    "label": "✏️ Введите новое название точки.",
    "coords": f"📍 Новые координаты.\n{COORDS_HELP}",
    "code": "🔑 Введите новый код точки.",
}


@admin_router.callback_query(F.data.regexp(r"^admin:edit:(label|coords|code):\d+$"), _admin_event)
async def cb_edit(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, field, raw_id = callback.data.split(":")
    await state.set_state(AdminEdit.value)
    await state.update_data(field=field, point_id=int(raw_id))
    await _show(callback, _EDIT_PROMPTS[field] + CANCEL_HINT)


async def _save_point_field(message: Message, state: FSMContext, **fields) -> None:
    data = await state.get_data()
    point_id = data["point_id"]
    await db.update_point(point_id, **fields)
    await state.clear()
    point = await db.get_point(point_id)
    if not point:
        await message.answer("Точка не найдена.", reply_markup=admin_points_menu(await db.get_points()))
        return
    await message.answer(
        f"✅ Сохранено.{await _warn_suffix()}\n\n{_point_card(point)}",
        reply_markup=admin_point_actions(point_id),
    )


@admin_router.message(AdminEdit.value, F.location, _admin_event)
async def msg_edit_geo(message: Message, state: FSMContext) -> None:
    if (await state.get_data()).get("field") != "coords":
        await message.answer("❌ Ожидается текст, а не геопозиция.")
        return
    await _save_point_field(message, state, lat=message.location.latitude, lon=message.location.longitude)


@admin_router.message(AdminEdit.value, _admin_event, _text_msg)
async def msg_edit_text(message: Message, state: FSMContext) -> None:
    field = (await state.get_data()).get("field")
    value = message.text.strip()
    if field == "coords":
        parsed = parse_coords(value)
        if parsed is None:
            await message.answer(f"❌ Неверный формат.\n{COORDS_HELP}")
            return
        await _save_point_field(message, state, lat=parsed[0], lon=parsed[1])
    elif field in ("label", "code") and value:
        await _save_point_field(message, state, **{field: value})
    elif field == "team_name" and value:
        await _save_team_name(message, state, value)
    else:
        await message.answer("❌ Значение не может быть пустым.")


# ── Final hint ────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:hint", _admin_event)
async def cb_hint(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    current = await db.get_setting("final_hint")
    shown = html.escape(current) if current else "не задана"
    await _show(callback, f"🏁 Финальная подсказка:\n\n{shown}", admin_hint_menu())


@admin_router.callback_query(F.data == "admin:hintset", _admin_event)
async def cb_hint_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminHint.text)
    await _show(callback, "🏁 Введите новый текст финальной подсказки (его увидят команды после последней точки)." + CANCEL_HINT)


@admin_router.message(AdminHint.text, _admin_event, _text_msg)
async def msg_hint(message: Message, state: FSMContext) -> None:
    await db.set_setting("final_hint", message.text.strip())
    await state.clear()
    await message.answer("✅ Подсказка сохранена.", reply_markup=admin_main_menu())


# ── Teams ─────────────────────────────────────────────────────────────────────

async def _show_teams(callback: CallbackQuery, prefix: str = "") -> None:
    teams = await db.list_teams()
    body = "👥 Команды (имя — пароль — позиция):" if teams else "👥 Команд пока нет."
    await _show(callback, prefix + body, admin_teams_menu(teams))


@admin_router.callback_query(F.data == "admin:teams", _admin_event)
async def cb_teams(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _show_teams(callback)


@admin_router.callback_query(F.data.startswith("admin:team:"), _admin_event)
async def cb_team(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    team = await db.get_team(_tail_id(callback))
    if not team:
        await callback.answer("Команда не найдена", show_alert=True)
        return
    if team["finished_at"]:
        status = "🏁 финишировала"
    elif team["started_at"]:
        status = f"на точке {team['current_position']}"
    else:
        status = "не стартовала"
    test = " 🧪 тестовая" if team["is_test"] else ""
    await _show(
        callback,
        f"<b>{html.escape(team['name'] or '')}</b>{test}\n\n"
        f"🔑 Пароль: <code>{html.escape(team['password'])}</code>\nСтатус: {status}",
        admin_team_actions(team["id"]),
    )


@admin_router.callback_query(F.data == "admin:tnew", _admin_event)
async def cb_teams_new(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminTeams.count)
    await _show(callback, f"👥 Сколько команд создать? (1–{MAX_TEAMS_AT_ONCE})" + CANCEL_HINT)


@admin_router.message(AdminTeams.count, _admin_event, _text_msg)
async def msg_teams_count(message: Message, state: FSMContext) -> None:
    n = parse_count(message.text)
    if n is None:
        await message.answer(f"❌ Введите число от 1 до {MAX_TEAMS_AT_ONCE}.")
        return
    try:
        teams = await db.create_teams(n)
    except ValueError as exc:
        await state.clear()
        await message.answer(f"❌ {html.escape(str(exc))}", reply_markup=admin_main_menu())
        return
    await state.clear()
    lines = [f"{html.escape(team['name'])} — <code>{html.escape(team['password'])}</code>" for team in teams]
    await message.answer("✅ Созданы команды:\n\n" + "\n".join(lines))
    await message.answer("👥 Команды", reply_markup=admin_teams_menu(await db.list_teams()))


@admin_router.callback_query(F.data == "admin:ttest", _admin_event)
async def cb_team_test(callback: CallbackQuery) -> None:
    team = (await db.create_teams(1, is_test=True))[0]
    await callback.message.answer(
        f"🧪 Тестовая команда: {html.escape(team['name'])} — <code>{html.escape(team['password'])}</code>\n"
        "Введите пароль в боте, чтобы пройти маршрут."
    )
    await _show_teams(callback)


@admin_router.callback_query(F.data.startswith("admin:tname:"), _admin_event)
async def cb_team_rename(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminEdit.value)
    await state.update_data(field="team_name", team_id=_tail_id(callback))
    await _show(callback, "✏️ Введите новое название команды." + CANCEL_HINT)


async def _save_team_name(message: Message, state: FSMContext, name: str) -> None:
    team_id = (await state.get_data())["team_id"]
    await db.rename_team(team_id, name)
    await state.clear()
    await message.answer("✅ Команда переименована.", reply_markup=admin_teams_menu(await db.list_teams()))


@admin_router.callback_query(F.data.startswith("admin:tdel:"), _admin_event)
async def cb_team_delete(callback: CallbackQuery) -> None:
    team = await db.get_team(_tail_id(callback))
    if not team:
        await callback.answer("Команда не найдена", show_alert=True)
        return
    await _show(
        callback,
        f"🗑 Удалить команду «{html.escape(team['name'] or '')}»? Участники и прогресс будут удалены.",
        admin_confirm(f"admin:tdelok:{team['id']}", f"admin:team:{team['id']}", "✅ Да, удалить"),
    )


@admin_router.callback_query(F.data.startswith("admin:tdelok:"), _admin_event)
async def cb_team_delete_ok(callback: CallbackQuery) -> None:
    await db.delete_team(_tail_id(callback))
    await _show_teams(callback, prefix="✅ Команда удалена.\n\n")


# ── Results ───────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:results", _admin_event)
async def cb_results(callback: CallbackQuery) -> None:
    rows = await db.get_results()
    chunks = format_results(rows, TZ) + format_breakdown(rows, TZ)
    await callback.answer()
    for chunk in chunks:
        await callback.message.answer(chunk)
    await callback.message.answer("📊 Результаты выше.", reply_markup=admin_back("admin:main"))


# ── Reset ─────────────────────────────────────────────────────────────────────

@admin_router.callback_query(F.data == "admin:reset", _admin_event)
async def cb_reset(callback: CallbackQuery) -> None:
    await _show(callback, "♻️ Сброс прогресса (команды и пароли остаются):", admin_reset_menu())


@admin_router.callback_query(F.data.in_({"admin:resetall", "admin:resettest"}), _admin_event)
async def cb_reset_ask(callback: CallbackQuery) -> None:
    test_only = callback.data == "admin:resettest"
    what = "тестовых команд" if test_only else "ВСЕХ боевых команд"
    await _show(
        callback,
        f"♻️ Сбросить прогресс {what}? Старт, финиш и взятые точки будут стёрты.",
        admin_confirm(f"admin:resetok:{int(test_only)}", "admin:reset", "✅ Да, сбросить"),
    )


@admin_router.callback_query(F.data.regexp(r"^admin:resetok:[01]$"), _admin_event)
async def cb_reset_ok(callback: CallbackQuery) -> None:
    await db.reset_progress(test_only=bool(_tail_id(callback)))
    await _show(callback, "✅ Прогресс сброшен.", admin_main_menu())
