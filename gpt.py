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
