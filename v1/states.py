from aiogram.fsm.state import State, StatesGroup


class AdminPoint(StatesGroup):
    waiting_label = State()
    waiting_coords = State()
    waiting_photo = State()


class AdminSettings(StatesGroup):
    waiting_value = State()
