#states.py
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
    decline_reason = State()

class AdminStates(StatesGroup):
    processing_appointment = State()
    selecting_date = State()
    selecting_specialist = State()

class SpecialistStates(StatesGroup):
    rating_client = State()
    confirm_work = State()
