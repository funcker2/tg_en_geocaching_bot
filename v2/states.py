from aiogram.fsm.state import State, StatesGroup


class PlayerLogin(StatesGroup):
    waiting_password = State()


class AdminPoint(StatesGroup):
    label = State()
    coords = State()
    code = State()


class AdminEdit(StatesGroup):
    value = State()


class AdminTeams(StatesGroup):
    count = State()


class AdminHint(StatesGroup):
    text = State()
