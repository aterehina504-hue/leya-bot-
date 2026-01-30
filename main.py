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
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
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
    user_access[callback.from_user.id] = time.time() + 86400
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
    expires = user_access.get(message.from_user.id, 0)

    if time.time() > expires:
        await message.answer(
            "⏳ Тестовый доступ завершён.\n\n"
            "Чтобы продолжить путь с Леей, оформи подписку 🤍"
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
    await start_webserver()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
