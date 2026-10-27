from aiogram.fsm.state import State, StatesGroup


class PlayerLogin(StatesGroup):
    waiting_password = State()
