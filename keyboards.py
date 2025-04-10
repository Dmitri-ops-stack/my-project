from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def client_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новая заявка")],
            [KeyboardButton(text="📋 Мои заявки")]
        ],
        resize_keyboard=True,
        persistent=True
    )

def admin_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📅 Записи")],
            [KeyboardButton(text="🔨 ЧС"), KeyboardButton(text="👥 Специалисты")]
        ],
        resize_keyboard=True,
        persistent=True
    )

def specialist_main_keyboard(has_appointments: bool = False):
    keyboard = [
        [KeyboardButton(text="📅 Расписание"), KeyboardButton(text="📊 Отчеты")]
    ]
    if has_appointments:
        keyboard.insert(0, [KeyboardButton(text="✅ Готов к работе")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        persistent=True
    )

def confirmation_keyboard(appointment_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{appointment_id}"),
             InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{appointment_id}")]
        ]
    )

def rating_keyboard(appointment_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(i), callback_data=f"rate_{i}_{appointment_id}") for i in range(1, 6)]
        ]
    )