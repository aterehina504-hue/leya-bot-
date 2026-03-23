import asyncio
import json
import os
import time
from datetime import datetime

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from dotenv import load_dotenv

from guides import GUIDES, PRICE_EXPERIMENTS
from storage import (
    init_db,
    add_days,
    get_expires,
    has_subscription,
    get_ab_group,
    save_payment,
    get_revenue_stats,
    get_all_active_users,
    get_users_for_reminder,
    mark_reminded,
    set_subscription_from_recurring,
    get_recurring_info,
    set_recurring_status,
)

from gpt import ask_guide

import random

from paths import PATH_DAYS
from insights import INSIGHT_TEMPLATES
from storage import get_user_day, update_activity

# ======================
# CONFIG
# ======================
MAX_HISTORY = 6
REMINDER_CHECK_INTERVAL = 60 * 60          # 1 час
REMINDER_BEFORE_SECONDS = 24 * 60 * 60     # за 24 часа
SUBSCRIPTION_PERIOD_SECONDS = 2592000      # 30 дней recurring Stars

# Paywall-триггер
TRIAL_PAYWALL_AFTER_MESSAGES = 3
DEEP_PAYWALL_AFTER_MESSAGES = 5

# ======================
# ENV
# ======================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "8080"))
ADMIN_IDS = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ======================
# STATES
# ======================
class UserState(StatesGroup):
    SELECT_GUIDE = State()
    GUIDE_MENU = State()
    GUIDE_ACTIVE = State()


# ======================
# MARKETING COPY / FUNNEL
# ======================

WELCOME_TEXT = (
    "Ты не сломана.\n"
    "Ты просто давно не слышала себя.\n\n"
    "Здесь ты можешь:\n"
    "— разобраться в своих чувствах\n"
    "— понять, чего ты хочешь\n"
    "— перестать быть удобной\n"
    "— вернуть внутреннюю опору\n\n"
    "Выбери проводника, с которым хочешь пройти этот этап 🤍"
)

GUIDE_COPY = {
    "leya": {
        "name": "Лея",
        "emoji": "🤍",
        "focus": "вернуться к себе и снова услышать свои чувства",
        "result": "ты уже начала лучше слышать себя",
        "pain": "ты снова можешь отложить себя на потом",
    },
    "amira": {
        "name": "Амира",
        "emoji": "🌼",
        "focus": "вернуть уважение к себе и укрепить границы",
        "result": "ты уже начала по-другому относиться к себе",
        "pain": "ты снова можешь поставить себя не на первое место",
    },
    "elira": {
        "name": "Элира",
        "emoji": "🌸",
        "focus": "снова услышать свои желания и живой отклик",
        "result": "ты уже начала лучше слышать свои желания",
        "pain": "ты снова можешь заглушить своё «хочу»",
    },
    "nera": {
        "name": "Нера",
        "emoji": "🔥",
        "focus": "вернуть внутреннюю опору и почувствовать свою силу",
        "result": "ты уже начала возвращать внутреннюю опору",
        "pain": "ты снова можешь остаться с этим напряжением одна",
    },
}

RETENTION_MESSAGES = {
    "pre_expiry_24h": [
        "Ты только начала слышать себя.\n\nСейчас самый важный момент — не остановиться.",
        "Ты уже не в той точке, где была в начале.\n\nВажно не потерять этот контакт с собой.",
    ],
    "expired": [
        "Твой доступ завершился.\n\nНо твой процесс не закончился.",
        "Жаль обрывать этот путь именно сейчас.\n\nТы уже начала важный внутренний процесс.",
    ],
}


# ======================
# HELPERS
# ======================

def stars_text(amount: int) -> str:
    return f"{amount // 100} ⭐"


def format_dt(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


def get_plan_by_code(guide_key: str, plan_code: str, user_id: int):
    prices = PRICE_EXPERIMENTS[guide_key]
    if plan_code == "7d":
        ab_group = get_ab_group(user_id, guide_key)
        return prices[ab_group], ab_group
    return prices[plan_code], None


def build_trial_paywall_text(guide_key: str, user_id: int) -> str:
    g = GUIDE_COPY[guide_key]
    p7, _ = get_plan_by_code(guide_key, "7d", user_id)
    pm, _ = get_plan_by_code(guide_key, "monthly", user_id)
    pr, _ = get_plan_by_code(guide_key, "recurring", user_id)

    return (
        f"{g['emoji']} Ты сейчас коснулась важного.\n\n"
        f"Обычно именно в этом месте мы снова откладываем себя на потом.\n"
        f"Но ты уже начала путь, где можешь {g['focus']}.\n\n"
        f"Выбери формат, который тебе сейчас подходит:\n\n"
        f"— {p7['label']} • мягко пойти глубже уже сейчас\n"
        f"— {pm['label']} • для более устойчивого результата\n"
        f"— {pr['label']} • самый выгодный способ не прерываться\n\n"
        f"Ты не обязана разбираться со всем одна."
    )


def build_deep_paywall_text(guide_key: str, user_id: int) -> str:
    g = GUIDE_COPY[guide_key]
    p7, _ = get_plan_by_code(guide_key, "7d", user_id)
    pm, _ = get_plan_by_code(guide_key, "monthly", user_id)
    pr, _ = get_plan_by_code(guide_key, "recurring", user_id)

    return (
        f"{g['emoji']} Ты сейчас сказала очень важную вещь.\n\n"
        f"И здесь есть два пути:\n"
        f"— снова закрыть это и {g['pain']}\n"
        f"— или пойти глубже и правда разобраться с тем, что внутри\n\n"
        f"Я могу быть рядом в этом процессе.\n\n"
        f"Выбери формат, который тебе сейчас подходит:\n\n"
        f"— {p7['label']} • начать уже сейчас\n"
        f"— {pm['label']} • пройти глубже и не обрываться\n"
        f"— {pr['label']} • самый выгодный формат продолжения"
    )


def build_renewal_paywall_text(guide_key: str, user_id: int) -> str:
    g = GUIDE_COPY[guide_key]
    p7, _ = get_plan_by_code(guide_key, "7d", user_id)
    pm, _ = get_plan_by_code(guide_key, "monthly", user_id)
    pr, _ = get_plan_by_code(guide_key, "recurring", user_id)

    return (
        f"{g['emoji']} {g['result']}.\n\n"
        f"Самое ценное сейчас — не потерять этот контакт с собой.\n\n"
        f"Продолжить можно так:\n\n"
        f"— {pm['label']} • мягкое продолжение без обрыва\n"
        f"— {pr['label']} • выгоднее и проще не прерываться\n"
        f"— {p7['label']} • если хочешь продлить пока только на неделю"
    )


def build_expired_paywall_text(guide_key: str, user_id: int) -> str:
    g = GUIDE_COPY[guide_key]
    p7, _ = get_plan_by_code(guide_key, "7d", user_id)
    pm, _ = get_plan_by_code(guide_key, "monthly", user_id)
    pr, _ = get_plan_by_code(guide_key, "recurring", user_id)

    return (
        f"{g['emoji']} Твой доступ завершился, но твой процесс не закончился.\n\n"
        f"Ты уже начала путь, где можешь {g['focus']}.\n"
        f"Жаль терять это именно сейчас.\n\n"
        f"Вернуться можно так:\n\n"
        f"— {p7['label']} • мягко вернуться на неделю\n"
        f"— {pm['label']} • продолжить глубже и стабильнее\n"
        f"— {pr['label']} • самый удобный формат, чтобы не выпадать"
    )


def guides_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=guide["title"], callback_data=f"guide_{key}")]
            for key, guide in GUIDES.items()
        ]
    )


def guide_menu_keyboard(guide_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🕊 Попробовать 24 часа",
                    callback_data=f"test_{guide_key}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💎 Посмотреть тарифы",
                    callback_data=f"tariffs_{guide_key}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌿 Назад к выбору",
                    callback_data="back_to_guides"
                )
            ],
        ]
    )


def tariffs_keyboard(user_id: int, guide_key: str) -> InlineKeyboardMarkup:
    ab_group = get_ab_group(user_id, guide_key)
    prices = PRICE_EXPERIMENTS[guide_key]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💎 {prices[ab_group]['label']}",
                    callback_data=f"buy:{guide_key}:{ab_group}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🌙 {prices['monthly']['label']}",
                    callback_data=f"buy:{guide_key}:monthly"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔁 {prices['recurring']['label']}",
                    callback_data=f"sub:{guide_key}:recurring"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌿 Вернуться к проводнику",
                    callback_data=f"guide_{guide_key}"
                )
            ],
        ]
    )


def paywall_keyboard(user_id: int, guide_key: str, renewal: bool = False) -> InlineKeyboardMarkup:
    ab_group = get_ab_group(user_id, guide_key)
    prices = PRICE_EXPERIMENTS[guide_key]

    rows = []
    if renewal:
        rows.append([
            InlineKeyboardButton(
                text=f"🌙 {prices['monthly']['label']}",
                callback_data=f"buy:{guide_key}:monthly"
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"🔁 {prices['recurring']['label']}",
                callback_data=f"sub:{guide_key}:recurring"
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"💎 {prices[ab_group]['label']}",
                callback_data=f"buy:{guide_key}:{ab_group}"
            )
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                text=f"💎 {prices[ab_group]['label']}",
                callback_data=f"buy:{guide_key}:{ab_group}"
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"🌙 {prices['monthly']['label']}",
                callback_data=f"buy:{guide_key}:monthly"
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"🔁 {prices['recurring']['label']}",
                callback_data=f"sub:{guide_key}:recurring"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="🌿 Вернуться к проводнику",
            callback_data=f"guide_{guide_key}"
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def expired_keyboard(user_id: int, guide_key: str) -> InlineKeyboardMarkup:
    ab_group = get_ab_group(user_id, guide_key)
    prices = PRICE_EXPERIMENTS[guide_key]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💎 {prices[ab_group]['label']}", callback_data=f"buy:{guide_key}:{ab_group}")],
            [InlineKeyboardButton(text=f"🌙 {prices['monthly']['label']}", callback_data=f"buy:{guide_key}:monthly")],
            [InlineKeyboardButton(text=f"🔁 {prices['recurring']['label']}", callback_data=f"sub:{guide_key}:recurring")],
            [InlineKeyboardButton(text="🌿 К выбору проводника", callback_data="back_to_guides")],
        ]
    )


def recurring_manage_keyboard(guide_key: str, active: bool) -> InlineKeyboardMarkup:
    if active:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⏸ Отключить автопродление", callback_data=f"cancel_sub:{guide_key}")],
                [InlineKeyboardButton(text="💎 Открыть тарифы", callback_data=f"tariffs_{guide_key}")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Включить автопродление", callback_data=f"resume_sub:{guide_key}")],
            [InlineKeyboardButton(text="💎 Открыть тарифы", callback_data=f"tariffs_{guide_key}")],
        ]
    )


async def create_recurring_invoice_link(guide_key: str, amount: int) -> str:
    """
    Telegram recurring Stars subscription via createInvoiceLink.
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink"
    payload = {
        "title": GUIDES[guide_key]["title"],
        "description": "Автоподписка с ежемесячным продлением в Stars",
        "payload": f"recurring:{guide_key}:recurring",
        "provider_token": "",
        "currency": "XTR",
        "prices": json.dumps([{"label": "Автоподписка", "amount": amount}]),
        "subscription_period": SUBSCRIPTION_PERIOD_SECONDS,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(str(data))
            return data["result"]


async def edit_user_star_subscription(user_id: int, telegram_payment_charge_id: str, is_canceled: bool) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editUserStarSubscription"
    payload = {
        "user_id": user_id,
        "telegram_payment_charge_id": telegram_payment_charge_id,
        "is_canceled": str(is_canceled).lower(),
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(str(data))


def user_has_paid_access(user_id: int, guide_key: str) -> bool:
    exp = get_expires(user_id, guide_key)
    return bool(exp and exp > time.time())


def should_show_trial_paywall(message_count: int, trial_active: bool, is_paid: bool) -> bool:
    if is_paid:
        return False
    return trial_active and message_count >= TRIAL_PAYWALL_AFTER_MESSAGES


def should_show_deep_paywall(message_count: int, trial_active: bool, is_paid: bool) -> bool:
    if is_paid:
        return False
    return trial_active and message_count >= DEEP_PAYWALL_AFTER_MESSAGES


# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.set_state(UserState.SELECT_GUIDE)
    await state.update_data(
        history=[],
        active_guide=None,
        trial_active=False,
        message_count_in_session=0,
        paywall_stage=None,
    )
    await message.answer(
        WELCOME_TEXT,
        reply_markup=guides_keyboard()
    )

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

    user_id = message.from_user.id

    # ===== проверка доступа =====
    expires = get_expires(user_id, guide_key)
    if not expires or expires <= time.time():
        await state.update_data(trial_active=False)
        await message.answer(
            build_expired_paywall_text(guide_key, user_id),
            reply_markup=expired_keyboard(user_id, guide_key)
        )
        return

    history = data.get("history", [])
    trial_active = bool(data.get("trial_active"))
    paywall_stage = data.get("paywall_stage")
    message_count = int(data.get("message_count_in_session", 0))

    # ===== день пользователя =====
    day = get_user_day(user_id, guide_key)
    update_activity(user_id, guide_key)

    # ===== сценарный старт =====
    if message_count == 0:
        if guide_key in PATH_DAYS and day in PATH_DAYS[guide_key]:
            await message.answer(
                random.choice(PATH_DAYS[guide_key][day])
            )

    # увеличиваем счетчик
    message_count += 1

    # ===== GPT =====
    temp_history = history + [{"role": "user", "content": message.text}]

    reply = await ask_guide(
        guide_key=guide_key,
        message=message.text,
        history=temp_history
    )

    history = (temp_history + [{"role": "assistant", "content": reply}])[-MAX_HISTORY:]

    await state.update_data(
        history=history,
        message_count_in_session=message_count
    )

    await message.answer(reply)

    # ===== инсайт =====
    if random.random() < 0.2:
        await message.answer("Как будто это повторяется в твоей жизни")

    # ===== привязанность =====
    if random.random() < 0.25:
        await message.answer("Я рядом с тобой в этом")

    # ===== day-based paywall =====
    if day == 3 and message_count >= 2:
        await message.answer(
            "Ты сейчас очень близко к тому, чтобы разобраться.\n\n"
            "Хочешь продолжить?",
            reply_markup=paywall_keyboard(user_id, guide_key, renewal=False)
        )

    # ========= PAYWALL ВНУТРИ ДИАЛОГА =========
    if should_show_trial_paywall(
        message_count=message_count,
        trial_active=trial_active,
        is_paid=False,
    ) and paywall_stage is None:
        await asyncio.sleep(0.4)
        await message.answer(
            build_trial_paywall_text(guide_key, user_id),
            reply_markup=paywall_keyboard(user_id, guide_key, renewal=False)
        )
        await state.update_data(paywall_stage="trial_shown")
        return

    if should_show_deep_paywall(
        message_count=message_count,
        trial_active=trial_active,
        is_paid=False,
    ) and paywall_stage == "trial_shown":
        await asyncio.sleep(0.4)
        await message.answer(
            build_deep_paywall_text(guide_key, user_id),
            reply_markup=paywall_keyboard(user_id, guide_key, renewal=False)
        )
        await state.update_data(paywall_stage="deep_shown")

# ======================
# GUIDE MENU
# ======================
@dp.callback_query(F.data.startswith("guide_"))
async def select_guide(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    guide_key = callback.data.replace("guide_", "")
    guide = GUIDES.get(guide_key)

    if not guide:
        await callback.message.answer("Проводник не найден.")
        return

    await state.set_state(UserState.GUIDE_MENU)
    await state.update_data(
        active_guide=guide_key,
        history=[],
        message_count_in_session=0,
        paywall_stage=None,
    )

    intro_text = guide.get("intro_text") or guide.get("menu_text") or "Я рядом."
    await callback.message.answer(
        f"{guide['title']}\n\n{intro_text}",
        reply_markup=guide_menu_keyboard(guide_key)
    )


@dp.callback_query(F.data == "back_to_guides")
async def back_to_guides(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.SELECT_GUIDE)
    await state.update_data(
        active_guide=None,
        history=[],
        trial_active=False,
        message_count_in_session=0,
        paywall_stage=None,
    )
    await callback.message.answer(
        "Выбери проводника 🤍",
        reply_markup=guides_keyboard()
    )


# ======================
# TEST ACCESS
# ======================
@dp.callback_query(F.data.startswith("test_"))
async def start_test(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    guide_key = callback.data.replace("test_", "")
    guide = GUIDES.get(guide_key)
    if not guide:
        await callback.message.answer("Проводник не найден.")
        return

    add_days(callback.from_user.id, guide_key, 1)

    await state.set_state(UserState.GUIDE_ACTIVE)
    await state.update_data(
        active_guide=guide_key,
        history=[],
        trial_active=True,
        message_count_in_session=0,
        paywall_stage=None,
    )

    await callback.message.answer(guide["test_text"])


# ======================
# TARIFFS
# ======================
@dp.callback_query(F.data.startswith("tariffs_"))
async def show_tariffs(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()

    guide_key = callback.data.replace("tariffs_", "")
    if guide_key not in GUIDES:
        await callback.message.answer("Проводник не найден.")
        return

    data = await state.get_data()
    trial_active = bool(data.get("trial_active"))

    text = build_trial_paywall_text(guide_key, callback.from_user.id)
    if not trial_active and has_subscription(callback.from_user.id, guide_key):
        text = build_renewal_paywall_text(guide_key, callback.from_user.id)

    await callback.message.answer(
        text,
        reply_markup=paywall_keyboard(callback.from_user.id, guide_key, renewal=has_subscription(callback.from_user.id, guide_key))
    )


# ======================
# ONE-TIME BUY
# ======================
@dp.callback_query(F.data.startswith("buy:"))
async def buy(callback: types.CallbackQuery):
    await callback.answer()

    _, guide_key, tariff_key = callback.data.split(":")
    tariff = PRICE_EXPERIMENTS.get(guide_key, {}).get(tariff_key)

    if not tariff:
        await callback.message.answer("Тариф не найден.")
        return

    description = f"Доступ на {tariff['days']} дней"
    if tariff_key == "monthly":
        description = "Доступ на 30 дней"
    elif tariff_key in {"A", "B"}:
        description = f"Доступ на {tariff['days']} дней"

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=GUIDES[guide_key]["title"],
        description=description,
        payload=f"buy:{guide_key}:{tariff_key}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Доступ", amount=tariff["price"])],
    )


# ======================
# RECURRING SUBSCRIPTION
# ======================
@dp.callback_query(F.data.startswith("sub:"))
async def recurring_subscribe(callback: types.CallbackQuery):
    await callback.answer()

    _, guide_key, tariff_key = callback.data.split(":")
    tariff = PRICE_EXPERIMENTS.get(guide_key, {}).get(tariff_key)

    if not tariff:
        await callback.message.answer("Тариф не найден.")
        return

    try:
        link = await create_recurring_invoice_link(guide_key, tariff["price"])
    except Exception as e:
        await callback.message.answer(f"Не удалось создать автоподписку: {e}")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Оформить автоподписку", url=link)]
        ]
    )

    await callback.message.answer(
        "Автоподписка оформляется через Telegram 🤍\n\n"
        "Это самый удобный формат, чтобы не выпадать из процесса.\n"
        "После первой оплаты Telegram будет продлевать доступ автоматически каждые 30 дней.",
        reply_markup=kb
    )


@dp.callback_query(F.data.startswith("cancel_sub:"))
async def cancel_sub(callback: types.CallbackQuery):
    await callback.answer()

    guide_key = callback.data.split(":")[1]
    info = get_recurring_info(callback.from_user.id, guide_key)

    if not info or not info["recurring_charge_id"]:
        await callback.message.answer("Активная автоподписка не найдена.")
        return

    try:
        await edit_user_star_subscription(
            user_id=callback.from_user.id,
            telegram_payment_charge_id=info["recurring_charge_id"],
            is_canceled=True,
        )
        set_recurring_status(callback.from_user.id, guide_key, False)
        await callback.message.answer(
            f"Автопродление отключено.\n"
            f"Текущий доступ останется до {format_dt(info['recurring_expires_at'])} 🤍",
            reply_markup=recurring_manage_keyboard(guide_key, active=False)
        )
    except Exception as e:
        await callback.message.answer(f"Не удалось отключить автопродление: {e}")


@dp.callback_query(F.data.startswith("resume_sub:"))
async def resume_sub(callback: types.CallbackQuery):
    await callback.answer()

    guide_key = callback.data.split(":")[1]
    info = get_recurring_info(callback.from_user.id, guide_key)

    if not info or not info["recurring_charge_id"]:
        await callback.message.answer("Подписка для возобновления не найдена.")
        return

    try:
        await edit_user_star_subscription(
            user_id=callback.from_user.id,
            telegram_payment_charge_id=info["recurring_charge_id"],
            is_canceled=False,
        )
        set_recurring_status(callback.from_user.id, guide_key, True)
        await callback.message.answer(
            "Автопродление снова включено 🤍",
            reply_markup=recurring_manage_keyboard(guide_key, active=True)
        )
    except Exception as e:
        await callback.message.answer(f"Не удалось включить автопродление: {e}")


# ======================
# PRE CHECKOUT
# ======================
@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)


# ======================
# SUCCESS PAYMENT
# ======================
@dp.message(F.successful_payment)
async def successful_payment(message: types.Message, state: FSMContext):
    sp = message.successful_payment
    payload = sp.invoice_payload

    try:
        mode, guide_key, tariff_key = payload.split(":")
    except ValueError:
        await message.answer("Оплата получена, но payload не распознан.")
        return

    ab_group = tariff_key if tariff_key in {"A", "B"} else None

    save_payment(
        user_id=message.from_user.id,
        guide_key=guide_key,
        tariff_key=tariff_key,
        amount=sp.total_amount,
        currency=sp.currency,
        tg_charge_id=sp.telegram_payment_charge_id,
        is_recurring=bool(getattr(sp, "is_recurring", False)),
        is_first_recurring=bool(getattr(sp, "is_first_recurring", False)),
        subscription_expiration_date=getattr(sp, "subscription_expiration_date", None),
        ab_group=ab_group,
    )

    if mode == "buy":
        days = PRICE_EXPERIMENTS[guide_key][tariff_key]["days"]
        new_exp = add_days(message.from_user.id, guide_key, days)

        await state.set_state(UserState.GUIDE_ACTIVE)
        await state.update_data(
            active_guide=guide_key,
            history=[],
            trial_active=False,
            message_count_in_session=0,
            paywall_stage=None,
        )

        after_payment_text = GUIDES[guide_key].get("after_payment") or (
            f"💎 Оплата прошла!\n\n"
            f"Доступ активирован до {format_dt(new_exp)}.\n\n"
            f"Ты здесь. И это уже шаг к себе 🤍"
        )

        await message.answer(
            f"{after_payment_text}\n\nДоступ до {format_dt(new_exp)}"
        )
        return

    if mode == "recurring":
        sub_exp = getattr(sp, "subscription_expiration_date", None)
        if not sub_exp:
            sub_exp = int(time.time()) + SUBSCRIPTION_PERIOD_SECONDS

        set_subscription_from_recurring(
            user_id=message.from_user.id,
            guide_key=guide_key,
            expires_at=sub_exp,
            charge_id=sp.telegram_payment_charge_id,
            active=True,
        )

        await state.set_state(UserState.GUIDE_ACTIVE)
        await state.update_data(
            active_guide=guide_key,
            history=[],
            trial_active=False,
            message_count_in_session=0,
            paywall_stage=None,
        )

        await message.answer(
            f"🔁 Автоподписка активирована!\n\n"
            f"Текущий период до {format_dt(sub_exp)}.\n"
            f"Это самый удобный формат, чтобы не выпадать из процесса 🤍",
            reply_markup=recurring_manage_keyboard(guide_key, active=True)
        )
        return

    await message.answer("Оплата получена 🤍")


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
        await state.update_data(trial_active=False)
        await message.answer(
            build_expired_paywall_text(guide_key, message.from_user.id),
            reply_markup=expired_keyboard(message.from_user.id, guide_key)
        )
        return

    history = data.get("history", [])
    trial_active = bool(data.get("trial_active"))
    paywall_stage = data.get("paywall_stage")
    message_count = int(data.get("message_count_in_session", 0)) + 1

    temp_history = history + [{"role": "user", "content": message.text}]

    reply = await ask_guide(
        guide_key=guide_key,
        message=message.text,
        history=temp_history
    )

    history = (temp_history + [{"role": "assistant", "content": reply}])[-MAX_HISTORY:]

    await state.update_data(
        history=history,
        message_count_in_session=message_count
    )

    await message.answer(reply)

    # ========= PAYWALL ВНУТРИ ДИАЛОГА =========
    # Если триал активен, показываем paywall после нескольких сообщений.
    if should_show_trial_paywall(
        message_count=message_count,
        trial_active=trial_active,
        is_paid=False,  # здесь triал тоже не считаем платным
    ) and paywall_stage is None:
        await asyncio.sleep(0.4)
        await message.answer(
            build_trial_paywall_text(guide_key, message.from_user.id),
            reply_markup=paywall_keyboard(message.from_user.id, guide_key, renewal=False)
        )
        await state.update_data(paywall_stage="trial_shown")
        return

    if should_show_deep_paywall(
        message_count=message_count,
        trial_active=trial_active,
        is_paid=False,
    ) and paywall_stage == "trial_shown":
        await asyncio.sleep(0.4)
        await message.answer(
            build_deep_paywall_text(guide_key, message.from_user.id),
            reply_markup=paywall_keyboard(message.from_user.id, guide_key, renewal=False)
        )
        await state.update_data(paywall_stage="deep_shown")


# ======================
# USER COMMANDS
# ======================
@dp.message(Command("status"))
async def status_cmd(message: types.Message, state: FSMContext):
    data = await state.get_data()
    guide_key = data.get("active_guide")

    if not guide_key:
        await message.answer("Сначала выбери проводника 🤍", reply_markup=guides_keyboard())
        return

    expires = get_expires(message.from_user.id, guide_key)
    info = get_recurring_info(message.from_user.id, guide_key)
    recurring_active = bool(info["recurring_active"]) if info else False

    await message.answer(
        f"Проводник: {GUIDES[guide_key]['title']}\n"
        f"Доступ до: {format_dt(expires)}\n"
        f"Автопродление: {'включено' if recurring_active else 'выключено'}",
        reply_markup=recurring_manage_keyboard(guide_key, recurring_active)
        if info and info["recurring_charge_id"] else None
    )


@dp.message(Command("tariffs"))
async def tariffs_cmd(message: types.Message, state: FSMContext):
    data = await state.get_data()
    guide_key = data.get("active_guide")

    if not guide_key:
        await message.answer("Сначала выбери проводника 🤍", reply_markup=guides_keyboard())
        return

    await message.answer(
        build_trial_paywall_text(guide_key, message.from_user.id),
        reply_markup=paywall_keyboard(message.from_user.id, guide_key, renewal=False)
    )


# ======================
# ADMIN
# ======================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    active_users = get_all_active_users()
    total, by_tariff, by_ab = get_revenue_stats()

    lines = [
        "👑 Админка",
        f"Активных пользователей: {len(active_users)}",
        f"Выручка всего: {stars_text(total['total'])}",
        f"Платежей всего: {total['cnt']}",
        "",
        "По тарифам:",
    ]

    for row in by_tariff[:20]:
        lines.append(
            f"• {row['guide_key']} / {row['tariff_key']}: "
            f"{stars_text(row['amount'])} ({row['cnt']} оплат)"
        )

    if by_ab:
        lines.append("")
        lines.append("A/B:")
        for row in by_ab:
            lines.append(
                f"• {row['guide_key']} / {row['ab_group']}: "
                f"{stars_text(row['amount'])} ({row['cnt']} оплат)"
            )

    await message.answer("\n".join(lines))


@dp.message(Command("revenue"))
async def revenue_cmd(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    total, by_tariff, by_ab = get_revenue_stats()
    lines = [
        f"💰 Выручка: {stars_text(total['total'])}",
        f"Платежей: {total['cnt']}",
        "",
        "Тарифы:",
    ]

    for row in by_tariff[:20]:
        lines.append(
            f"• {row['guide_key']} / {row['tariff_key']}: "
            f"{stars_text(row['amount'])}"
        )

    if by_ab:
        lines.append("")
        lines.append("A/B цены:")
        for row in by_ab:
            lines.append(
                f"• {row['guide_key']} / {row['ab_group']}: "
                f"{stars_text(row['amount'])} ({row['cnt']} оплат)"
            )

    await message.answer("\n".join(lines))


@dp.message(Command("broadcast"))
async def broadcast(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast текст")
        return

    text = parts[1]
    users = get_all_active_users()
    sent = 0

    for user_id in users:
        try:
            await bot.send_message(user_id, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await message.answer(f"Отправлено: {sent}")


# ======================
# REMINDERS
# ======================
async def reminder_worker():
    """
    Сейчас worker использует только существующий storage API:
    get_users_for_reminder(REMINDER_BEFORE_SECONDS)

    То есть он работает на продление перед окончанием доступа.
    Для полноценного inactive / expired winback дальше стоит добавить в storage:
    - get_users_for_inactive_return(...)
    - get_users_for_expired_winback(...)
    """
    while True:
        try:
            rows = get_users_for_reminder(REMINDER_BEFORE_SECONDS)

            for row in rows:
                guide_key = row["guide_key"]
                recurring_active = bool(row["recurring_active"])
                user_id = row["user_id"]

                if recurring_active:
                    text = (
                        f"{GUIDE_COPY[guide_key]['emoji']} Напоминаю: доступ к {GUIDES[guide_key]['title']} "
                        f"скоро продлится автоматически, если на балансе Stars достаточно средств.\n\n"
                        f"Ты уже в процессе — хорошо бы его не обрывать 🤍"
                    )
                    reply_markup = recurring_manage_keyboard(guide_key, active=True)
                else:
                    base = RETENTION_MESSAGES["pre_expiry_24h"][user_id % len(RETENTION_MESSAGES["pre_expiry_24h"])]
                    text = (
                        f"{GUIDE_COPY[guide_key]['emoji']} {base}\n\n"
                        f"{build_renewal_paywall_text(guide_key, user_id)}"
                    )
                    reply_markup = paywall_keyboard(user_id, guide_key, renewal=True)

                try:
                    await bot.send_message(user_id, text, reply_markup=reply_markup)
                    mark_reminded(user_id, guide_key)
                    await asyncio.sleep(0.05)
                except Exception:
                    pass

        except Exception as e:
            print("REMINDER ERROR:", e)

        await asyncio.sleep(REMINDER_CHECK_INTERVAL)


# ======================
# HEALTHCHECK
# ======================
async def healthcheck(request):
    return web.Response(text="OK")


async def start_webserver():
    app = web.Application()
    app.router.add_get("/", healthcheck)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()


# ======================
# MAIN
# ======================
async def main():
    init_db()
    asyncio.create_task(reminder_worker())
    await start_webserver()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
