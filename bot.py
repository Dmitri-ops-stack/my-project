import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove
from sqlalchemy import select, func, update
from config import API_TOKEN, ADMIN_ID, SPECIALISTS, TIMEZONE, CODEWORD
from database import AsyncSessionMaker, Client, Specialist, Appointment, Blacklist, Rating, init_db, StatusEnum, \
    ClientStatus
from states import ClientStates, AdminStates, SpecialistStates
from keyboards import *
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler()


async def check_blacklist(user_id: int):
    async with AsyncSessionMaker() as session:
        result = await session.execute(
            select(Blacklist).where(Blacklist.client_id == user_id)
        return result.scalar_one_or_none()


async def get_user_role(user_id: int):
    if user_id == ADMIN_ID:
        return "admin"
    async with AsyncSessionMaker() as session:
        specialist = await session.execute(
            select(Specialist).where(Specialist.telegram_id == user_id))
        if specialist.scalar():
            return "specialist"
        client = await session.execute(
            select(Client).where(Client.telegram_id == user_id))
        return "client" if client.scalar() else None


@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    role = await get_user_role(user_id)

    if role == "admin":
        await message.answer("Панель администратора", reply_markup=admin_main_keyboard())
    elif role == "specialist":
        async with AsyncSessionMaker() as session:
            has_appointments = await session.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.specialist_id == user_id,
                    Appointment.status == StatusEnum.approved))
        await message.answer("Панель специалиста", reply_markup=specialist_main_keyboard(has_appointments > 0))
    else:
        if await check_blacklist(user_id):
            await message.answer("🚫 Вы в черном списке!", reply_markup=ReplyKeyboardRemove())
            return
        await message.answer("Добро пожаловать! Введите кодовое слово:")
        await state.set_state(ClientStates.await_codeword)


@dp.message(ClientStates.await_codeword)
async def process_codeword(message: types.Message, state: FSMContext):
    if message.text != CODEWORD:
        await message.answer("❌ Неверное кодовое слово!")
        return
    await state.update_data(telegram_id=message.from_user.id)
    await message.answer("Введите ваше полное имя:")
    await state.set_state(ClientStates.registration)


@dp.message(ClientStates.registration)
async def process_registration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_step = data.get("reg_step", 0)

    steps = [
        ("name", "Введите ваш город:"),
        ("city", "Введите место работы:"),
        ("workplace", "Введите тип изделия:"),
        ("product_type", "Введите серийный номер:"),
        ("serial_number", "Введите ваш телефон:")
    ]

    if current_step < len(steps):
        field, prompt = steps[current_step]
        await state.update_data({field: message.text, "reg_step": current_step + 1})
        await message.answer(prompt)
    else:
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
        await message.answer("✅ Регистрация завершена!", reply_markup=client_main_keyboard())
        await state.clear()


@dp.message(F.text == "📝 Новая заявка")
async def new_request(message: types.Message, state: FSMContext):
    await message.answer("Опишите проблему:")
    await state.set_state(ClientStates.collecting_reason)


@dp.message(ClientStates.collecting_reason)
async def process_reason(message: types.Message, state: FSMContext):
    async with AsyncSessionMaker() as session:
        client = await session.execute(
            select(Client).where(Client.telegram_id == message.from_user.id))
        client = client.scalar()

        new_appointment = Appointment(
            client_id=client.id,
            description=message.text,
            created_at=datetime.now(pytz.utc),
            status=StatusEnum.pending
        )
        session.add(new_appointment)
        await session.commit()
        await message.answer("✅ Заявка создана!", reply_markup=client_main_keyboard())
        await state.clear()


@dp.message(F.text == "📋 Мои заявки")
async def show_appointments(message: types.Message):
    async with AsyncSessionMaker() as session:
        client = await session.execute(
            select(Client).where(Client.telegram_id == message.from_user.id))
        client = client.scalar()

        appointments = await session.execute(
            select(Appointment)
            .where(Appointment.client_id == client.id)
            .order_by(Appointment.created_at.desc()))

        text = "Ваши заявки:\n\n"
        for app in appointments.scalars():
            text += f"▫️ {app.created_at.astimezone(TIMEZONE).strftime('%d.%m.%Y %H:%M')}\n"
            text += f"Статус: {app.status.value}\n\n"
        await message.answer(text or "У вас нет активных заявок")


@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with AsyncSessionMaker() as session:
        total_clients = await session.scalar(select(func.count(Client.id)))
        active_apps = await session.scalar(
            select(func.count(Appointment.id)).where(Appointment.status == StatusEnum.approved))
        await message.answer(f"📊 Статистика:\nКлиентов: {total_clients}\nАктивных заявок: {active_apps}")


@dp.message(F.text == "🔨 ЧС")
async def manage_blacklist(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with AsyncSessionMaker() as session:
        entries = await session.execute(select(Blacklist))
        text = "Черный список:\n"
        for entry in entries.scalars():
            text += f"ID {entry.client_id} до {entry.until.strftime('%d.%m.%Y')}\n"
        await message.answer(text or "Список пуст")


@dp.message(F.text == "👥 Специалисты")
async def manage_specialists(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with AsyncSessionMaker() as session:
        specs = await session.execute(select(Specialist))
        text = "Специалисты:\n"
        for spec in specs.scalars():
            text += f"▫️ {spec.name} ({spec.username}) - {'🟢' if spec.is_available else '🔴'}\n"
        await message.answer(text or "Нет специалистов")


@dp.message(F.text == "✅ Готов к работе")
async def toggle_availability(message: types.Message):
    async with AsyncSessionMaker() as session:
        spec = await session.execute(
            select(Specialist).where(Specialist.telegram_id == message.from_user.id))
        spec = spec.scalar()

        now = datetime.now(pytz.utc)
        active = await session.scalar(
            select(Appointment).where(
                Appointment.specialist_id == spec.id,
                Appointment.status == StatusEnum.approved,
                Appointment.date >= now - timedelta(minutes=30),
                Appointment.date <= now + timedelta(hours=1)))

        if not active:
            await message.answer("❌ Нет активных записей")
            return

        spec.is_available = not spec.is_available
        await session.commit()
        status = "🟢 Доступен" if spec.is_available else "🔴 Занят"
        await message.answer(status)


@dp.message(F.text == "📅 Расписание")
async def show_schedule(message: types.Message):
    async with AsyncSessionMaker() as session:
        spec = await session.execute(
            select(Specialist).where(Specialist.telegram_id == message.from_user.id))
        spec = spec.scalar()

        apps = await session.execute(
            select(Appointment)
            .where(Appointment.specialist_id == spec.id)
            .order_by(Appointment.date))

        text = "Расписание:\n"
        for app in apps.scalars():
            text += f"▫️ {app.date.astimezone(TIMEZONE).strftime('%d.%m %H:%M')} - {app.client.name}\n"
        await message.answer(text or "Нет записей")


async def on_startup():
    await init_db()
    async with AsyncSessionMaker() as session:
        for tg_id, spec in SPECIALISTS.items():
            exists = await session.execute(
                select(Specialist).where(Specialist.telegram_id == tg_id))
            if not exists.scalar():
                session.add(Specialist(
                    telegram_id=tg_id,
                    name=spec['name'],
                    username=spec['username']))
        await session.commit()
    scheduler.start()


if __name__ == '__main__':
    dp.startup.register(on_startup)
    dp.run_polling(bot)