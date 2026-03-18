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

# ======================
# CONFIG
# ======================
MAX_HISTORY = 6
REMINDER_CHECK_INTERVAL = 60 * 60          # 1 час
REMINDER_BEFORE_SECONDS = 24 * 60 * 60     # за 24 часа
SUBSCRIPTION_PERIOD_SECONDS = 2592000      # 30 дней для recurring Stars

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
# HELPERS
# ======================
def stars_text(amount: int) -> str:
    return f"{amount // 100} ⭐"


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


def expired_keyboard(guide_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Продлить доступ", callback_data=f"tariffs_{guide_key}")],
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


def format_dt(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


# ======================
# START
# ======================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.set_state(UserState.SELECT_GUIDE)
    await state.update_data(history=[])
    await message.answer(
        "Я рядом 🤍\n\nВыбери проводника:",
        reply_markup=guides_keyboard()
    )


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
    await state.update_data(active_guide=guide_key, history=[])

    await callback.message.answer(
        f"{guide['title']}\n\n{guide['menu_text']}",
        reply_markup=guide_menu_keyboard(guide_key)
    )


@dp.callback_query(F.data == "back_to_guides")
async def back_to_guides(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserState.SELECT_GUIDE)
    await state.update_data(active_guide=None, history=[])
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
    await state.update_data(active_guide=guide_key, history=[])

    await callback.message.answer(guide["test_text"])


# ======================
# TARIFFS
# ======================
@dp.callback_query(F.data.startswith("tariffs_"))
async def show_tariffs(callback: types.CallbackQuery):
    await callback.answer()

    guide_key = callback.data.replace("tariffs_", "")
    if guide_key not in GUIDES:
        await callback.message.answer("Проводник не найден.")
        return

    await callback.message.answer(
        "Выбери формат доступа 🤍",
        reply_markup=tariffs_keyboard(callback.from_user.id, guide_key)
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

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=GUIDES[guide_key]["title"],
        description=f"Доступ на {tariff['days']} дней",
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
        "Автоподписка оформляется по ссылке Telegram 🤍\n\n"
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
        await state.update_data(active_guide=guide_key, history=[])

        await message.answer(
            f"💎 Оплата прошла!\n"
            f"Доступ активирован до {format_dt(new_exp)} 🤍"
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
        await state.update_data(active_guide=guide_key, history=[])

        await message.answer(
            f"🔁 Автоподписка активирована!\n"
            f"Текущий период до {format_dt(sub_exp)} 🤍",
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
        await message.answer(
            "⏳ Доступ завершён.\n\nТы можешь продолжить путь 🤍",
            reply_markup=expired_keyboard(guide_key)
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

    await state.update_data(history=history)
    await message.answer(reply)


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
    while True:
        try:
            rows = get_users_for_reminder(REMINDER_BEFORE_SECONDS)

            for row in rows:
                guide_key = row["guide_key"]
                recurring_active = bool(row["recurring_active"])

                if recurring_active:
                    text = (
                        f"Напоминаю: доступ к {GUIDES[guide_key]['title']} "
                        f"скоро продлится автоматически, если на балансе Stars достаточно средств 🤍"
                    )
                    reply_markup = recurring_manage_keyboard(guide_key, active=True)
                else:
                    text = (
                        f"Напоминаю: доступ к {GUIDES[guide_key]['title']} "
                        f"закончится меньше чем через 24 часа 🤍\n\n"
                        f"Чтобы не прерывать путь, продли доступ заранее."
                    )
                    reply_markup = expired_keyboard(guide_key)

                try:
                    await bot.send_message(row["user_id"], text, reply_markup=reply_markup)
                    mark_reminded(row["user_id"], guide_key)
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
