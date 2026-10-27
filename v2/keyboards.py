from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from texts import BTN_SHARE_LOCATION


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SHARE_LOCATION, request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )
