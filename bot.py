import logging
from datetime import datetime, timedelta
import pytz
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import joinedload
from sqlalchemy import update, delete
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from sqlalchemy import select, func
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandObject
from config import API_TOKEN, ADMIN_ID, SPECIALISTS, TIMEZONE, CODEWORD
from database import AsyncSessionMaker, Client, Specialist, Appointment, Blacklist, init_db, StatusEnum, ClientStatus
from states import ClientStates, AdminStates, SpecialistStates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from keyboards import client_main_keyboard, admin_main_keyboard, specialist_main_keyboard, confirmation_keyboard

# Logging
logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()

# Check blacklist
async def check_blacklist(user_id: int):
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Blacklist).where(Blacklist.client_id == user_id)
        )
        entry = res.scalar_one_or_none()
        if entry and entry.until > datetime.now(pytz.utc):
            return True
    return False

# Determine user role
async def get_user_role(user_id: int):
    if user_id == ADMIN_ID:
        return 'admin'
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Specialist).where(Specialist.telegram_id == user_id)
        )
        if res.scalar_one_or_none():
            return 'specialist'
        res = await session.execute(
            select(Client).where(Client.telegram_id == user_id)
        )
        if res.scalar_one_or_none():
            return 'client'
    return None

# Start handler
@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    role = await get_user_role(user_id)
    if role == 'admin':
        await message.answer('Панель администратора', reply_markup=admin_main_keyboard())
    elif role == 'specialist':
        async with AsyncSessionMaker() as session:
            count = await session.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.specialist_id == user_id,
                    Appointment.status == StatusEnum.approved
                )
            )
        await message.answer('Панель специалиста', reply_markup=specialist_main_keyboard(count > 0))
    else:
        if await check_blacklist(user_id):
            await message.answer('🚫 Вы в черном списке!', reply_markup=ReplyKeyboardRemove())
            return
        await message.answer('Добро пожаловать! Введите кодовое слово:')
        await state.set_state(ClientStates.await_codeword)

# Process codeword
@dp.message(ClientStates.await_codeword)
async def process_codeword(message: types.Message, state: FSMContext):
    if message.text.strip() != CODEWORD:
        await message.answer('❌ Неверное кодовое слово!')
        return
    await state.update_data(telegram_id=message.from_user.id, reg_step=0)
    await message.answer('Введите ваше полное имя:')
    await state.set_state(ClientStates.registration)

# Registration multi-step
@dp.message(ClientStates.registration)
async def process_registration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_step = data.get('reg_step', 0)
    steps = [
        ('name', 'Введите ваш город:'),
        ('city', 'Введите место работы:'),
        ('workplace', 'Введите тип изделия:'),
        ('product_type', 'Введите серийный номер:'),
        ('serial_number', 'Введите ваш телефон:')
    ]
    if current_step == 0:
        # first step: name
        await state.update_data(name=message.text)
    elif current_step <= len(steps):
        # subsequent steps
        field, prompt = steps[current_step-1]
        await state.update_data({field: message.text})
    if current_step < len(steps):
        # ask next
        _, prompt = steps[current_step]
        await message.answer(prompt)
        await state.update_data(reg_step=current_step+1)
    else:
        # all data collected
        async with AsyncSessionMaker() as session:
            data = await state.get_data()
            client = Client(
                telegram_id=data['telegram_id'],
                name=data['name'],
                city=data['city'],
                workplace=data['workplace'],
                product_type=data['product_type'],
                serial_number=data['serial_number'],
                phone=message.text,
                status=ClientStatus.active
            )
            session.add(client)
            await session.commit()
        await message.answer('✅ Регистрация завершена!', reply_markup=client_main_keyboard())
        await state.clear()

# New request
@dp.message(F.text == '📝 Новая заявка')
async def new_request(message: types.Message, state: FSMContext):
    await message.answer('Опишите проблему:')
    await state.set_state(ClientStates.collecting_reason)

# Process reason
@dp.message(ClientStates.collecting_reason)
async def process_reason(message: types.Message, state: FSMContext):
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Client).where(Client.telegram_id == message.from_user.id)
        )
        client = res.scalar_one()

        appointment = Appointment(
            client_id=client.id,
            description=message.text,
            created_at=datetime.now(pytz.utc),
            status=StatusEnum.pending
        )
        session.add(appointment)
        await session.commit()

    # ✉️ Уведомление админу
    await bot.send_message(
        ADMIN_ID,
        f"📩 Новая заявка #{appointment.id} от {client.name}:\n\n{message.text}",
        reply_markup=confirmation_keyboard(appointment.id)
    )

    await message.answer('✅ Заявка создана!', reply_markup=client_main_keyboard())
    await state.clear()

# Обработка подтверждения/отмены
@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_appointment(callback: types.CallbackQuery, state: FSMContext):
    appointment_id = int(callback.data.split("_")[1])
    await state.update_data(appointment_id=appointment_id)
    await callback.message.edit_reply_markup()  # Удаляем кнопки
    await callback.message.answer("📅 Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ")
    await state.set_state(AdminStates.selecting_date)


@dp.message(AdminStates.selecting_date)
async def process_date(message: types.Message, state: FSMContext):
    try:
        date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        date = TIMEZONE.localize(date)
        await state.update_data(appointment_date=date)

        # Получаем доступных специалистов
        async with AsyncSessionMaker() as session:
            specialists = await session.scalars(
                select(Specialist).where(Specialist.is_available == True)
            )
            specialists = specialists.all()

        # Создаем кнопки
        keyboard = InlineKeyboardMarkup(inline_keyboard=[])
        for spec in specialists:
            keyboard.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{spec.name} ({spec.username})",
                    callback_data=f"spec_{spec.id}"
                )
            ])

        await message.answer("👥 Выберите специалиста:", reply_markup=keyboard)
        await state.set_state(AdminStates.selecting_specialist)

    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")


# В обработчике process_specialist (полная версия)
@dp.callback_query(F.data.startswith("spec_"))
async def process_specialist(callback: types.CallbackQuery, state: FSMContext):
    specialist_id = int(callback.data.split("_")[1])
    data = await state.get_data()

    try:
        async with AsyncSessionMaker() as session:
            res = await session.execute(
                select(Appointment)
                .options(joinedload(Appointment.client))
                .where(Appointment.id == data['appointment_id'])
            )
            appointment = res.scalar_one()

            specialist = await session.get(Specialist, specialist_id)

            # Уведомление специалисту (исправленная версия)
            await bot.send_message(
                specialist.telegram_id,
                f"📌 Новая задача!\n"
                f"🗓 Дата: {appointment.date.astimezone(TIMEZONE).strftime('%d.%m.%Y %H:%M')}\n"
                f"👤 Клиент: {appointment.client.name}\n"
                f"📍 Город: {appointment.client.city}\n"
                f"📱 Телефон: {appointment.client.phone}\n"
                f"📦 Тип изделия: {appointment.client.product_type}\n"
                f"🔢 Серийный номер: {appointment.client.serial_number}\n"
                f"📝 Причина обращения:\n{appointment.description}"
            )

            # Уведомление клиенту с кнопками
            await bot.send_message(
                appointment.client.telegram_id,
                f"✅ Ваша заявка одобрена!\n"
                f"📅 Дата: {appointment.date.astimezone(TIMEZONE).strftime('%d.%m.%Y %H:%M')}\n"
                f"👨💻 Специалист: {specialist.name}\n"
                f"📎 Контакты: @{specialist.username}",
                reply_markup=client_confirm_keyboard(appointment.id)
            )

    except Exception as e:
        logging.error(f"Ошибка: {str(e)}", exc_info=True)


@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_appointment(callback: types.CallbackQuery):
    appointment_id = int(callback.data.split("_")[1])
    async with AsyncSessionMaker() as session:
        await session.execute(
            update(Appointment)
            .where(Appointment.id == appointment_id)
            .values(status=StatusEnum.canceled)
        )
        await session.commit()
    await callback.message.edit_text("❌ Заявка отменена")

# Show appointments
@dp.message(F.text == '📋 Мои заявки')
async def show_appointments(message: types.Message):
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Client).where(Client.telegram_id == message.from_user.id)
        )
        client = res.scalar_one_or_none()
        if not client:
            await message.answer('Сначала зарегистрируйтесь.')
            return
        res = await session.execute(
            select(Appointment).where(Appointment.client_id == client.id).order_by(Appointment.created_at.desc())
        )
        apps = res.scalars().all()
    if not apps:
        await message.answer('У вас нет активных заявок.')
        return
    text = 'Ваши заявки:\n\n'
    for app in apps:
        local_time = app.created_at.astimezone(TIMEZONE).strftime('%d.%m.%Y %H:%M')
        text += f'▫️ {local_time}\nСтатус: {app.status.value}\n\n'
    await message.answer(text)

# Show stats
@dp.message(F.text == '📊 Статистика')
async def show_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with AsyncSessionMaker() as session:
        total_clients = await session.scalar(select(func.count(Client.id)))
        active_apps = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.status == StatusEnum.approved)
        )
    await message.answer(f'📊 Статистика:\nКлиентов: {total_clients}\nАктивных заявок: {active_apps}')

# Manage blacklist
@dp.message(F.text == '🔨 ЧС')
async def manage_blacklist(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with AsyncSessionMaker() as session:
        res = await session.execute(select(Blacklist))
        entries = res.scalars().all()
    if not entries:
        await message.answer('Список пуст')
        return
    text = 'Черный список:\n'
    for entry in entries:
        until = entry.until.astimezone(TIMEZONE).strftime('%d.%m.%Y')
        text += f'ID {entry.client_id} до {until}\n'
    await message.answer(text)

# Manage specialists
@dp.message(F.text == '👥 Специалисты')
async def manage_specialists(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with AsyncSessionMaker() as session:
        res = await session.execute(select(Specialist))
        specs = res.scalars().all()
    if not specs:
        await message.answer('Нет специалистов')
        return
    text = 'Специалисты:\n'
    for spec in specs:
        status = '🟢' if spec.is_available else '🔴'
        text += f'▫️ {spec.name} ({spec.username}) - {status}\n'
    await message.answer(text)

# Toggle availability
@dp.message(F.text == '✅ Готов к работе')
async def toggle_availability(message: types.Message):
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Specialist).where(Specialist.telegram_id == message.from_user.id)
        )
        spec = res.scalar_one_or_none()
        if not spec:
            return
        now = datetime.now(pytz.utc)
        recent = await session.scalar(
            select(func.count(Appointment.id)).where(
                Appointment.specialist_id == spec.id,
                Appointment.status == StatusEnum.approved,
                Appointment.date >= now - timedelta(minutes=30),
                Appointment.date <= now + timedelta(hours=1)
            )
        )
        if not recent:
            await message.answer('❌ Нет активных записей')
            return
        spec.is_available = not spec.is_available
        await session.commit()
        status = '🟢 Доступен' if spec.is_available else '🔴 Занят'
        await message.answer(status)

# Show schedule
@dp.message(F.text == '📅 Расписание')
async def show_schedule(message: types.Message):
    async with AsyncSessionMaker() as session:
        res = await session.execute(
            select(Specialist).where(Specialist.telegram_id == message.from_user.id)
        )
        spec = res.scalar_one_or_none()
        if not spec:
            return
        res = await session.execute(
            select(Appointment).where(Appointment.specialist_id == spec.id).order_by(Appointment.date)
        )
        apps = res.scalars().all()
    if not apps:
        await message.answer('Нет записей')
        return
    text = 'Расписание:\n'
    for app in apps:
        time_str = app.date.astimezone(TIMEZONE).strftime('%d.%m %H:%M')
        client_name = app.client.name
        text += f'▫️ {time_str} - {client_name}\n'
    await message.answer(text)

# Startup
async def on_startup():
    await init_db()
    async with AsyncSessionMaker() as session:
        for tg_id, data in SPECIALISTS.items():
            res = await session.execute(
                select(Specialist).where(Specialist.telegram_id == tg_id)
            )
            if not res.scalar_one_or_none():
                session.add(Specialist(
                    telegram_id=tg_id,
                    name=data['name'],
                    username=data['username']
                ))
        await session.commit()
    scheduler.start()

if __name__ == '__main__':
    dp.startup.register(on_startup)
    dp.run_polling(bot)
