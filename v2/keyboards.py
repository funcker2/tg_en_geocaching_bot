from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from texts import BTN_SHARE_LOCATION


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SHARE_LOCATION, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ── Admin ─────────────────────────────────────────────────────────────────────


def _back(target: str = "admin:main") -> tuple[str, str]:
    return "◀️ Назад", target


def admin_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📍 Точки", callback_data="admin:points")
    b.button(text="🏁 Финальная подсказка", callback_data="admin:hint")
    b.button(text="👥 Команды", callback_data="admin:teams")
    b.button(text="📊 Результаты", callback_data="admin:results")
    b.button(text="♻️ Сброс", callback_data="admin:reset")
    b.adjust(1)
    return b.as_markup()


def admin_points_menu(points: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in points:
        ok = p.get("lat") is not None and p.get("lon") is not None and bool(p.get("code"))
        b.button(
            text=f"{'✅' if ok else '⚠️'} {p['position']}. {p.get('label') or 'без названия'}",
            callback_data=f"admin:pt:{p['id']}",
        )
    b.button(text="➕ Добавить точку", callback_data="admin:ptadd")
    b.button(text=_back()[0], callback_data=_back()[1])
    b.adjust(1)
    return b.as_markup()


def admin_point_actions(point_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👁 Как видит игрок", callback_data=f"admin:prev:{point_id}")
    b.button(text="✏️ Название", callback_data=f"admin:edit:label:{point_id}")
    b.button(text="📍 Координаты", callback_data=f"admin:edit:coords:{point_id}")
    b.button(text="🔑 Код", callback_data=f"admin:edit:code:{point_id}")
    b.button(text="⬆️ Выше", callback_data=f"admin:up:{point_id}")
    b.button(text="⬇️ Ниже", callback_data=f"admin:down:{point_id}")
    b.button(text="🗑 Удалить", callback_data=f"admin:ptdel:{point_id}")
    b.button(text=_back("admin:points")[0], callback_data="admin:points")
    b.adjust(1, 3, 2, 1, 1)
    return b.as_markup()


def admin_confirm(yes_data: str, no_data: str, yes_text: str = "✅ Да") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=yes_text, callback_data=yes_data)
    b.button(text="❌ Нет", callback_data=no_data)
    b.adjust(2)
    return b.as_markup()


def admin_back(target: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=_back(target)[0], callback_data=target)
    return b.as_markup()


def admin_hint_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Изменить", callback_data="admin:hintset")
    b.button(text=_back()[0], callback_data=_back()[1])
    b.adjust(1)
    return b.as_markup()


def admin_teams_menu(teams: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for team in teams:
        if team.get("finished_at"):
            status = "🏁 финиш"
        elif team.get("started_at"):
            status = f"точка {team['current_position']}"
        else:
            status = "не стартовала"
        mark = "🧪 " if team.get("is_test") else ""
        b.button(
            text=f"{mark}{team['name']} — {team['password']} — {status}",
            callback_data=f"admin:team:{team['id']}",
        )
    b.button(text="➕ Создать команды", callback_data="admin:tnew")
    b.button(text="🧪 Тестовая команда", callback_data="admin:ttest")
    b.button(text=_back()[0], callback_data=_back()[1])
    b.adjust(1)
    return b.as_markup()


def admin_team_actions(team_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Переименовать", callback_data=f"admin:tname:{team_id}")
    b.button(text="🗑 Удалить", callback_data=f"admin:tdel:{team_id}")
    b.button(text=_back("admin:teams")[0], callback_data="admin:teams")
    b.adjust(1)
    return b.as_markup()


def admin_reset_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="♻️ Сбросить игру (боевые команды)", callback_data="admin:resetall")
    b.button(text="🧪 Сбросить тестовые", callback_data="admin:resettest")
    b.button(text=_back()[0], callback_data=_back()[1])
    b.adjust(1)
    return b.as_markup()
