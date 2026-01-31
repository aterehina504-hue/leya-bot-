import asyncio
import os
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web

from guides import GUIDES
from storage import (
    init_db,
    get_leya_expires, add_leya_days,
    get_amira_expires, add_amira_days,
    get_elira_expires, add_elira_days,
    get_nera_expires, add_nera_days
)
from gpt import ask_leya, ask_amira, ask_elira, ask_nera
MAX_HISTORY = 6  # 3 пары user/assistant

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
    ONBOARDING = State()
    SELECT_GUIDE = State()
    GUIDE_MENU = State()
    GUIDE_ACTIVE = State()

# ======================
# HELPERS
# ======================
def format_date(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y")

def guides_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌷 Лея — путь к себе", callback_data="guide_leya")],
        [InlineKeyboardButton(text="🌼 Амира — путь к самоценности", callback_data="guide_amira")],
        [InlineKeyboardButton(text="🌸 Элира — путь к желаниям", callback_data="guide_elira")],
        [InlineKeyboardButton(text="🔥 Нера — путь к женской силе", callback_data="guide_nera")],
    ])

def payment_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💎 Перейти к оплате",
            url="https://t.me/lea_payment_bot"
        )],
        [InlineKeyboardButton(
            text="🌿 Вернуться к выбору",
            callback_data="back_to_guides"
        )]
    ])

# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext, command: CommandObject):
    data = await state.get_data()

    # --- возврат после оплаты ---
    if command.args in GUIDES:
        guide_key = command.args
        add_days = globals()[f"add_{guide_key}_days"]
        add_days(message.from_user.id, 7)

        await state.set_state(UserState.GUIDE_ACTIVE)
        await state.update_data(active_guide=guide_key)

        await message.answer(
            f"{GUIDES[guide_key]['title']}\n\n"
            "💎 Доступ активирован на 7 дней.\n"
            "Я рядом 🤍"
        )
        return

    # --- если онбординг уже был ---
    if data.get("onboarding_done"):
        await state.set_state(UserState.SELECT_GUIDE)
        await message.answer(
            "Я рядом 🤍\n\nВыбери проводника:",
            reply_markup=guides_keyboard()
        )
        return

    # --- первый вход ---
    await state.set_state(UserState.ONBOARDING)
    await message.answer(
        "Привет 🤍\n\n"
        "Это пространство бережного диалога.\n"
        "Здесь не нужно быть «правильной».\n"
        "Можно просто быть.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Дальше 🌱", callback_data="onboard_1")]
        ])
    )

@dp.callback_query(lambda c: c.data == "onboard_1")
async def onboarding_step_1(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    await callback.message.answer(
        "Здесь ты можешь:\n\n"
        "— выговориться\n"
        "— побыть в тишине\n"
        "— услышать себя\n\n"
        "Я буду рядом и поддержу 🌿",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Поняла 🤍", callback_data="onboard_2")]
        ])
    )

@dp.callback_query(lambda c: c.data == "onboard_2")
async def onboarding_step_2(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    await state.update_data(
    onboarding_done=True,
    onboarding_time=time.time(),
    first_message_sent=False
)
    await state.set_state(UserState.SELECT_GUIDE)

    await callback.message.answer(
        "Ты можешь выбрать проводника —\n"
        "тот стиль, который откликается тебе сейчас 🤍",
        reply_markup=guides_keyboard()
    )

# ======================
# SELECT GUIDE
# ======================
@dp.callback_query(lambda c: c.data.startswith("guide_"))
async def select_guide(callback: types.CallbackQuery, state: FSMContext):
    guide_key = callback.data.replace("guide_", "")
    guide = GUIDES[guide_key]

    await callback.answer()
    await state.set_state(UserState.GUIDE_MENU)
    await state.update_data(active_guide=guide_key)

    await callback.message.answer(
        f"{guide['title']}\n\n{guide['menu_text']}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🕊 Попробовать 24 часа", callback_data="test")],
            [InlineKeyboardButton(text="💎 Оформить подписку", callback_data="buy")],
        ])
    )

# ======================
# TEST MODE
# ======================
@dp.callback_query(lambda c: c.data == "test")
async def start_test(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    guide_key = data["active_guide"]
    guide = GUIDES[guide_key]

    add_days = globals()[f"add_{guide_key}_days"]
    add_days(callback.from_user.id, 1)

    await state.set_state(UserState.GUIDE_ACTIVE)
    await callback.message.answer(guide["test_text"])

# ======================
# BUY
# ======================
@dp.callback_query(lambda c: c.data == "buy")
async def buy(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "💎 Оформление доступа на 7 дней.\n\n"
        "После оплаты ты вернёшься сюда.",
        reply_markup=payment_keyboard()
    )

# ======================
# DIALOG
# ======================
@dp.message(UserState.GUIDE_ACTIVE)
async def guide_dialog(message: types.Message, state: FSMContext):
    data = await state.get_data()
    guide_key = data["active_guide"]

    # --- напоминание после 3 дней тишины ---
    last_message_time = data.get("last_user_message_time")
    silence_reminder_sent = data.get("silence_3days_reminder_sent", False)

    if last_message_time and not silence_reminder_sent:
        if time.time() - last_message_time > 3 * 24 * 3600:
            await message.answer(
                "Я заметила паузу 🤍\n\n"
                "Иногда молчание — тоже часть пути.\n"
                "Если захочется вернуться — я здесь."
            )
            await state.update_data(silence_3days_reminder_sent=True)

    # --- напоминание через 24 часа после онбординга ---
    onboarding_time = data.get("onboarding_time")
    first_message_sent = data.get("first_message_sent", False)

    if onboarding_time and not first_message_sent:
        if time.time() - onboarding_time > 24 * 3600:
            await message.answer(
                "Я рядом 🤍\n\n"
                "Если захочется — можно просто написать пару слов."
            )
            await state.update_data(first_message_sent=True)

    # --- проверка доступа ---
    get_expires = globals()[f"get_{guide_key}_expires"]
    expires = get_expires(message.from_user.id)

    if time.time() > expires:
        await message.answer(
            "⏳ Доступ завершён.\n\n"
            "Ты можешь оформить подписку и продолжить путь 🤍",
            reply_markup=payment_keyboard()
        )
        return

    # --- напоминание за 1 день до окончания ---
    time_left = expires - time.time()
    reminder_key = f"expiry_reminder_{guide_key}"

    if 0 < time_left < 24 * 3600 and not data.get(reminder_key):
        await message.answer(
            "🤍 Хочу мягко напомнить:\n"
            "доступ скоро завершится.\n\n"
            "Если тебе важно продолжить — ты можешь продлить его в любой момент."
        )
        await state.update_data(**{reminder_key: True})

    # --- история диалога ---
    history = data.get("history", [])

    history.append({
        "role": "user",
        "content": message.text
    })
    history = history[-MAX_HISTORY:]

    ask_func = globals()[GUIDES[guide_key]["ask_func"]]
    reply = await ask_func(message.text, history=history)

    history.append({
        "role": "assistant",
        "content": reply
    })
    history = history[-MAX_HISTORY:]

    await state.update_data(
        history=history,
        last_user_message_time=time.time(),
        silence_3days_reminder_sent=False
    )

    await message.answer(reply)

# ======================
# BACK TO GUIDES
# ======================
@dp.callback_query(lambda c: c.data == "back_to_guides")
async def back_to_guides(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.SELECT_GUIDE)
    await callback.message.answer(
        "Выбери проводника:",
        reply_markup=guides_keyboard()
    )

# ======================
# WEB SERVER (RENDER)
# ======================
async def healthcheck(request):
    return web.Response(text="OK")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", healthcheck)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
site = web.TCPSite(runner, "0.0.0.0", port)
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
