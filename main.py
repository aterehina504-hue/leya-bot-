from aiogram.filters import CommandStart, CommandObject
import asyncio
import os
import time
from datetime import datetime
print("MAIN BOT: FILE LOADED")

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web

from guides import GUIDES
from storage import (
    init_db,
    get_expires, add_days,
    get_all_active_users,
    get_last_message_time,
    get_flag, set_flag
)
from gpt import ask_guide

# ======================
# CONFIG
# ======================
MAX_HISTORY = 6
CHECK_INTERVAL = 10 * 60  # 10 минут

# ======================
# ENV
# ======================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ======================
# STATES
# ======================
class UserState(StatesGroup):
    ONBOARDING = State()
    SELECT_GUIDE = State()
    GUIDE_MENU = State()
    GUIDE_ACTIVE = State()

# ======================
# HELPERS
# ======================
def guides_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=guide["title"],
                callback_data=f"guide_{key}"
            )]
            for key, guide in GUIDES.items()
        ]
    )

def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Перейти к оплате", url="https://t.me/lea_payment_bot")],
        [InlineKeyboardButton(text="🌿 Вернуться к выбору", callback_data="back_to_guides")]
    ])

# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext, command: CommandObject):
    # пользователь вернулся после оплаты
    if command.args in GUIDES:
        guide_key = command.args

        add_days(message.from_user.id, guide_key, 7)

        await state.set_state(UserState.GUIDE_ACTIVE)
        await state.update_data(active_guide=guide_key)

        await message.answer(
            f"{GUIDES[guide_key]['title']}\n\n"
            "💎 Доступ активирован.\n"
            "Я рядом 🤍"
        )
        return

    # обычный старт
    await state.set_state(UserState.SELECT_GUIDE)
    await message.answer(
        "Я рядом 🤍\n\nВыбери проводника:",
        reply_markup=guides_keyboard()
    )

# ======================
# SELECT GUIDE
# ======================
@dp.callback_query(lambda c: c.data.startswith("guide_"))
async def select_guide(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    guide_key = callback.data.replace("guide_", "")

    await state.clear()

    await state.set_state(UserState.GUIDE_MENU)
    await state.update_data(active_guide=guide_key)

    guide = GUIDES[guide_key]

    await callback.message.answer(
    f"{guide['title']}\n\n{guide['menu_text']}",
    reply_markup=InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🕊 Попробовать 24 часа",
                    callback_data=f"test_{guide_key}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Оформить доступ",
                    url="https://t.me/lea_payment_bot"
                )
            ],
        ]
    )
)

# ======================
# TEST
# ======================
@dp.callback_query(lambda c: c.data.startswith("test_"))
async def start_test(callback: types.CallbackQuery, state: FSMContext):
    guide_key = callback.data.replace("test_", "")

    await state.clear()
    await state.set_state(UserState.GUIDE_ACTIVE)
    await state.update_data(active_guide=guide_key)

    add_days(callback.from_user.id, guide_key, 1)

    await callback.message.answer(GUIDES[guide_key]["test_text"])

# ======================
# BUY
# ======================
@dp.callback_query(lambda c: c.data == "buy")
async def buy(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "💎 Доступ на 7 дней.\n\nПосле оплаты ты вернёшься сюда 🤍",
        reply_markup=payment_keyboard()
    )

# ======================
# DIALOG
# ======================
@dp.message(UserState.GUIDE_ACTIVE)
async def guide_dialog(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Я читаю только текст 🤍")
        return

    data = await state.get_data()
    guide_key = data.get("active_guide")

    if not guide_key:
        await state.set_state(UserState.SELECT_GUIDE)
        await message.answer("Выбери проводника 🤍", reply_markup=guides_keyboard())
        return

    expires = get_expires(message.from_user.id, guide_key)
    if not expires or expires <= time.time():
        await message.answer(
            "⏳ Доступ завершён.\n\nТы можешь продолжить путь 🤍",
            reply_markup=payment_keyboard()
        )
        return

    history = data.get("history", [])
    temp_history = history + [{"role": "user", "content": message.text}]

    reply = await ask_guide(
        guide_key=guide_key,
        message=message.text,
        history=temp_history
    )

    history = (temp_history + [{"role": "assistant", "content": reply}])[-MAX_HISTORY:]

    await state.update_data(
        history=history,
        last_message_time=time.time()
    )

    await message.answer(reply)

# ======================
# BACK
# ======================
@dp.callback_query(lambda c: c.data == "back_to_guides")
async def back(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.SELECT_GUIDE)
    await callback.message.answer("Выбери проводника:", reply_markup=guides_keyboard())

# ======================
# AUTOMATIC REMINDERS
# ======================
async def reminder_worker():
    while True:
        users = get_all_active_users()

        now = time.time()
        for user_id, guide_key, expires in users:
            # 3 дня тишины
            last = get_last_message_time(user_id)
            if last and now - last > 3 * 86400:
                if not get_flag(user_id, "silence_3d"):
                    await bot.send_message(
                        user_id,
                        "Я заметила паузу 🤍\n\nЕсли захочется вернуться — я здесь."
                    )
                    set_flag(user_id, "silence_3d")

            # 24 часа до окончания
            if 0 < expires - now < 86400:
                key = f"expiry_{guide_key}"
                if not get_flag(user_id, key):
                    await bot.send_message(
                        user_id,
                        "🤍 Доступ скоро завершится.\nЕсли важно продолжить — я рядом."
                    )
                    set_flag(user_id, key)

        await asyncio.sleep(CHECK_INTERVAL)

# ======================
# WEB SERVER
# ======================
async def healthcheck(request):
    return web.Response(text="OK")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", healthcheck)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# ======================
# MAIN
# ======================
async def main():
    print("MAIN BOT: main() started")

    init_db()

    await start_webserver()

    asyncio.get_running_loop().create_task(reminder_worker())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
