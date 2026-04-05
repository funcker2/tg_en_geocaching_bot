"""
Translations for user-facing strings.
Admin panel is always in Russian and is not included here.
"""

_S: dict[str, dict[str, str]] = {
    "ru": {
        "choose_language": "🌐 Выберите язык:",
        "btn_ru": "🇷🇺 Русский",
        "btn_bg": "🇧🇬 Български",
        "lang_set": "🇷🇺 Язык установлен: Русский",
        "btn_change_lang": "🌐 Сменить язык",
        # /start
        "welcome": (
            "👋 Добро пожаловать в квест!\n\n"
            "Поделитесь своей геолокацией, чтобы увидеть расстояния до точек."
        ),
        "btn_share_location": "📍 Поделиться геолокацией",
        # cooldown gate
        "cooldown_gate": (
            "⏳ Вы можете активировать следующую точку через:\n"
            "<b>{time}</b>\n\n"
            "Ожидайте или обратитесь к администратору."
        ),
        # distance list
        "point_not_configured": "не настроена",
        # refresh button
        "btn_refresh": "🔄 Обновить",
        "btn_refresh_countdown": "⏳ {sec}с",
        "refresh_locked": "⏳ Подождите...",
        "no_cached_location": "Сначала отправьте геолокацию.",
        # near-point prompt
        "at_point_prompt": "🎯 Вы у <b>{label}</b>!\n\nХотите активировать?",
        "btn_activate_yes": "✅ Да, активировать!",
        "btn_activate_no": "❌ Нет",
        "activate_declined": "Хорошо! Продолжайте исследование. 🗺",
        # activation errors
        "cooldown_active": "⏳ Кулдаун активен: {time}",
        "already_activated": "Вы уже активировали эту точку!",
        "too_far": "Вы слишком далеко от точки. Подойдите ближе.",
        # activation success
        "photo_caption": "🏆 Фрагмент <b>{label}</b> получен!",
        "no_photo": (
            "🏆 Вы активировали <b>{label}</b>!\n"
            "(фото ещё не загружено администратором)"
        ),
        # cooldown countdown message
        "cooldown_msg": (
            "⏳ Вы можете активировать следующую точку через:\n"
            "<b>{time}</b>"
        ),
        "cooldown_done": (
            "✅ Кулдаун снят!\n\n"
            "Поделитесь геолокацией, чтобы продолжить поиск."
        ),
        # cooldown shown on location share
        "cooldown_still": "⏳ Кулдаун активен. Следующая активация через <b>{time}</b>",
    },

    "bg": {
        "choose_language": "🌐 Изберете език:",
        "btn_ru": "🇷🇺 Русский",
        "btn_bg": "🇧🇬 Български",
        "lang_set": "🇧🇬 Избран език: Български",
        "btn_change_lang": "🌐 Смяна на езика",
        # /start
        "welcome": (
            "👋 Добре дошли в куеста!\n\n"
            "Споделете местоположението си, за да видите разстоянията до точките."
        ),
        "btn_share_location": "📍 Сподели местоположение",
        # cooldown gate
        "cooldown_gate": (
            "⏳ Можете да активирате следващата точка след:\n"
            "<b>{time}</b>\n\n"
            "Изчакайте или се свържете с администратора."
        ),
        # distance list
        "point_not_configured": "не е настроена",
        # refresh button
        "btn_refresh": "🔄 Обнови",
        "btn_refresh_countdown": "⏳ {sec}с",
        "refresh_locked": "⏳ Изчакайте...",
        "no_cached_location": "Първо изпратете местоположението си.",
        # near-point prompt
        "at_point_prompt": "🎯 Вие сте при <b>{label}</b>!\n\nИскате ли да активирате?",
        "btn_activate_yes": "✅ Да, активирай!",
        "btn_activate_no": "❌ Не",
        "activate_declined": "Добре! Продължете изследването. 🗺",
        # activation errors
        "cooldown_active": "⏳ Изчакване активно: {time}",
        "already_activated": "Вече сте активирали тази точка!",
        "too_far": "Твърде далеч сте от точката. Приближете се.",
        # activation success
        "photo_caption": "🏆 Фрагмент от <b>{label}</b> получен!",
        "no_photo": (
            "🏆 Активирахте <b>{label}</b>!\n"
            "(снимката все още не е качена от администратора)"
        ),
        # cooldown countdown message
        "cooldown_msg": (
            "⏳ Можете да активирате следващата точка след:\n"
            "<b>{time}</b>"
        ),
        "cooldown_done": (
            "✅ Изчакването приключи!\n\n"
            "Споделете местоположението си, за да продължите търсенето."
        ),
        # cooldown shown on location share
        "cooldown_still": "⏳ Изчакване активно. Следваща активация след <b>{time}</b>",
    },
}


def t(lang: str | None, key: str, **kwargs: object) -> str:
    """Return translated string for given language key, falling back to Russian."""
    lang = lang if lang in _S else "ru"
    text = _S[lang].get(key) or _S["ru"].get(key, key)
    return text.format(**kwargs) if kwargs else text
