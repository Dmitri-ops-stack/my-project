from aiogram.fsm.state import State, StatesGroup

class ClientStates(StatesGroup):
    await_codeword = State()
    registration = State()
    collecting_name = State()
    collecting_city = State()
    collecting_product = State()
    collecting_serial = State()
    collecting_date = State()
    collecting_reason = State()
    collecting_phone = State()

class AdminStates(StatesGroup):
    managing_blacklist = State()
    select_time = State()
    select_specialist = State()

class SpecialistStates(StatesGroup):
    rating_client = State()
    confirm_work = State()