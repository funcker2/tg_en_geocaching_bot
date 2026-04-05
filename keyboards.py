from aiogram.types import (
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from i18n import t


# ── Admin (always Russian) ────────────────────────────────────────────────────

def admin_main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚙️ Точки",      callback_data="admin:points")
    b.button(text="👥 Игроки",     callback_data="admin:players")
    b.button(text="🔧 Настройки",  callback_data="admin:settings")
    b.button(text="🎮 Играть как пользователь", callback_data="admin:play_as_user")
    b.adjust(3, 1)
    return b.as_markup()


def admin_points_menu(points: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in points:
        has_coords = p["lat"] is not None
        has_photo  = bool(p["photo_file_id"])
        if has_coords and has_photo:
            icon = "✅"
        elif has_coords or has_photo:
            icon = "⚠️"
        else:
            icon = "❌"
        b.button(text=f"{icon} {p['label']}", callback_data=f"admin:point:{p['id']}")
    b.button(text="◀️ Назад", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_point_actions(point_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📍 Изменить координаты", callback_data=f"admin:coords:{point_id}")
    b.button(text="🖼 Изменить фото",        callback_data=f"admin:photo:{point_id}")
    b.button(text="◀️ Назад",               callback_data="admin:points")
    b.adjust(1)
    return b.as_markup()


def admin_players_menu(users: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for u in users:
        cd_icon = "⏳ " if u["cooldown_until"] else ""
        pts     = u["points_count"]
        lang    = u.get("lang") or "—"
        b.button(
            text=f"{cd_icon}ID {u['user_id']} | точек: {pts} | {lang}",
            callback_data=f"admin:player:{u['user_id']}",
        )
    b.button(text="◀️ Назад", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


def admin_player_actions(user_id: int, has_cooldown: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if has_cooldown:
        b.button(text="🔓 Сбросить кулдаун", callback_data=f"admin:reset_cd:{user_id}")
    b.button(text="🗑 Сбросить прогресс полностью", callback_data=f"admin:reset_all:{user_id}")
    b.button(text="◀️ Назад", callback_data="admin:players")
    b.adjust(1)
    return b.as_markup()


def admin_settings_menu(refresh_sec: str, cooldown_min: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(
        text=f"🔄 Задержка обновления: {refresh_sec} с",
        callback_data="admin:set:refresh_delay_sec",
    )
    b.button(
        text=f"⏱ Кулдаун активации: {cooldown_min} мин",
        callback_data="admin:set:activation_cooldown_min",
    )
    b.button(text="◀️ Назад", callback_data="admin:main")
    b.adjust(1)
    return b.as_markup()


# ── User (language-aware) ─────────────────────────────────────────────────────

def language_select_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🇷🇺 Русский",    callback_data="user:lang:ru")
    b.button(text="🇧🇬 Български", callback_data="user:lang:bg")
    b.adjust(2)
    return b.as_markup()


def location_keyboard(lang: str = "ru") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text=t(lang, "btn_share_location"),
            request_location=True,
        )]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def refresh_keyboard(label: str | None = None, lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=label or t(lang, "btn_refresh"), callback_data="user:refresh")
    return b.as_markup()


def activate_keyboard(point_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_activate_yes"), callback_data=f"user:activate:{point_id}")
    b.button(text=t(lang, "btn_activate_no"),  callback_data="user:activate:no")
    b.adjust(2)
    return b.as_markup()
