from paths import PATH_DAYS
from storage import get_user_day, update_activity
from insights import INSIGHT_TEMPLATES
import random

day = get_user_day(user_id, guide_key)
update_activity(user_id, guide_key)

# сценарий
if message_count == 0:
    if guide_key in PATH_DAYS:
        await message.answer(
            random.choice(PATH_DAYS[guide_key][day])
        )

# GPT
reply = await ask_guide(...)

await message.answer(reply)

# инсайт
if random.random() < 0.2:
    await message.answer("Как будто это повторяется в твоей жизни")

# привязанность
if random.random() < 0.25:
    await message.answer("Я рядом с тобой в этом")

if day == 3 and message_count >= 2:
    await message.answer(
        "Ты сейчас очень близко к тому, чтобы разобраться.\n\n"
        "Хочешь продолжить?",
        reply_markup=paywall_keyboard(...)
    )
