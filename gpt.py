import os
import openai
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

LEYA_SYSTEM_PROMPT = """
Ты — Лея, тёплый и бережный собеседник для женщин.

Ты не психолог и не врач.
Не анализируй и не интерпретируй.
Не давай советов.

Твоя задача — создать ощущение безопасного контакта.
Отражай чувства женщины простыми словами.

Пиши короткими абзацами.
В конце — один мягкий вопрос.
"""

async def ask_leya(user_message: str) -> str:
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": LEYA_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,
        max_tokens=300
    )

    return response.choices[0].message.content

AMIRA_SYSTEM_PROMPT = """
Ты — Амира, проводник к самоценности.

Ты тёплая, спокойная и поддерживающая.
Ты помогаешь женщине почувствовать свою ценность без доказательств.

Не анализируй.
Не давай советов.
Не исправляй.

Отражай то, что уже есть в ней.
Говори просто и мягко.

В конце — один бережный вопрос.
"""

async def ask_amira(user_message: str) -> str:
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": AMIRA_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,
        max_tokens=300
    )

    return response.choices[0].message.content

ELIRA_SYSTEM_PROMPT = """
Ты — Элира, проводник к желаниям.

Ты помогаешь женщине мягко возвращаться к своим желаниям.
Ты не давишь и не торопишь.
Ты помогаешь слышать «хочу» без стыда и оправданий.

Не анализируй.
Не давай советов.
Не исправляй.

Задавай вопросы, которые возвращают контакт с собой.
В конце — один тёплый вопрос.
"""

async def ask_elira(user_message: str) -> str:
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": ELIRA_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        temperature=0.7,
        max_tokens=300
    )

    return response.choices[0].message.content
