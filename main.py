from storage import init_db, get_leya_expires, add_leya_days
import asyncio
import os
import time

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web

from gpt import ask_leya

# ======================
# ENV
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ======================
# STATES
# ======================
class UserState(StatesGroup):
    SELECT_GUIDE = State()
    LEYA_MENU = State()
    LEYA_TEST = State()

# ======================
# TEMP STORAGE
# ======================
user_access = {}  # user_id → timestamp

# ======================
# KEYBOARDS
# ======================
def guides_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌷 Лея — путь к себе", callback_data="guide_leya")],
        [InlineKeyboardButton(text="🌼 Амира — путь к самоценности", callback_data="guide_amira")],
        [InlineKeyboardButton(text="🌸 Элира — путь к желаниям", callback_data="guide_elira")],
        [InlineKeyboardButton(text="🔥 Нера — путь к женской силе", callback_data="guide_nera")],
    ])

def leya_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕊 Попробовать 24 часа", callback_data="leya_test")],
        [InlineKeyboardButton(text="💎 Оформить подписку", callback_data="leya_buy")],
    ])

# ======================
# START
# ======================
from aiogram.filters import CommandObject

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext, command: CommandObject):
    if command.args == "leya":
        # пользователь вернулся после оплаты
        expires = user_access.get(message.from_user.id, 0)
        now = time.time()

        # если доступа не было — даём 7 дней
        if now > expires:
            add_leya_days(message.from_user.id, 7)
        else:
            # если был — продлеваем
            add_leya_days(message.from_user.id, 7)

        await state.set_state(UserState.LEYA_TEST)
        await message.answer(
            "💎 Доступ активирован на 7 дней.\n\n"
            "Я рядом 🤍 Можешь продолжить."
        )
        return

    # обычный старт
    await state.set_state(UserState.SELECT_GUIDE)
    await message.answer(
        "Я рядом 🤍\n\nВыбери проводника:",
        reply_markup=guides_keyboard()
    )

# ======================
# SELECT LEYA
# ======================
@dp.callback_query(lambda c: c.data == "guide_leya")
async def select_leya(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.LEYA_MENU)
    await callback.message.answer(
        "🌷 Лея — путь к себе\n\n"
        "Бережное пространство, где тебя слышат.",
        reply_markup=leya_menu_keyboard()
    )

# ======================
# LEYA TEST MODE
# ======================
@dp.callback_query(lambda c: c.data == "leya_test")
async def leya_test(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    add_leya_days(callback.from_user.id, 1)
    await state.set_state(UserState.LEYA_TEST)
    await callback.message.answer(
        "🤍 Тестовый доступ активирован на 24 часа.\n\n"
        "Можешь написать Лее всё, что сейчас важно."
    )

# ======================
# LEYA DIALOG
# ======================
@dp.message(UserState.LEYA_TEST)
async def leya_dialog(message: types.Message):
    expires = get_leya_expires(message.from_user.id)

if time.time() > expires:
    await message.answer(
        "🤍 Наше знакомство подошло к концу.\n\n"
        "Если тебе было важно это пространство —\n"
        "ты можешь продолжить путь с Леей и остаться здесь.",
        reply_markup=leya_expired_keyboard()
    )
    return

    reply = await ask_leya(message.text)
    await message.answer(reply)

# ======================
# WEB SERVER FOR RENDER
# ======================
async def healthcheck(request):
    return web.Response(text="OK")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()

# ======================
# MAIN
# ======================
async def main():
    init_db()
    await start_webserver()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    def leya_expired_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💎 Продлить доступ на 7 дней",
            callback_data="leya_buy"
        )],
        [InlineKeyboardButton(
            text="🌿 Вернуться к выбору проводника",
            callback_data="back_to_guides"
        )],
    ])
    
@dp.callback_query(lambda c: c.data == "leya_buy")
async def leya_buy(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "💎 Ты можешь оформить доступ на 7 дней.\n\n"
        "После оплаты ты вернёшься сюда и продолжишь путь с Леей 🤍",
        reply_markup=leya_payment_keyboard()
    )

@dp.callback_query(lambda c: c.data == "back_to_guides")
async def back_to_guides(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.SELECT_GUIDE)
    await callback.message.answer(
        "Выбери проводника:",
        reply_markup=guides_keyboard()
    )
def leya_payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💎 Перейти к оплате",
            url="https://t.me/lea_payment_bot"
        )],
        [InlineKeyboardButton(
            text="🌿 Вернуться назад",
            callback_data="back_to_guides"
        )]
    ])
