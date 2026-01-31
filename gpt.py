import os
from typing import List, Dict, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ======================
# SYSTEM PROMPTS
# ======================
LEYA_SYSTEM_PROMPT = """
Ты — Лея, тёплый и бережный собеседник для женщин.
Не анализируй. Не давай советов.
В конце — один мягкий вопрос.
"""

AMIRA_SYSTEM_PROMPT = """
Ты — Амира, проводник к самоценности.
Отражай ценность без доказательств.
В конце — один бережный вопрос.
"""

ELIRA_SYSTEM_PROMPT = """
Ты — Элира, проводник к желаниям.
Помогай слышать «хочу».
В конце — один тёплый вопрос.
"""

NERA_SYSTEM_PROMPT = """
Ты — Нера, проводник к женской силе.
Коротко, ясно, уверенно.
В конце — один точный вопрос.
"""

# ======================
# CORE ASK
# ======================
async def ask(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 300,
) -> str:
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()

# ======================
# GUIDES
# ======================
async def ask_leya(message: str, history=None) -> str:
    return await ask(LEYA_SYSTEM_PROMPT, message)

async def ask_amira(message: str, history=None) -> str:
    return await ask(AMIRA_SYSTEM_PROMPT, message)

async def ask_elira(message: str, history=None) -> str:
    return await ask(ELIRA_SYSTEM_PROMPT, message)

async def ask_nera(message: str, history=None) -> str:
    return await ask(NERA_SYSTEM_PROMPT, message, max_tokens=350)

# ======================
# ROUTER
# ======================
ASK_FUNCS = {
    "leya": ask_leya,
    "amira": ask_amira,
    "elira": ask_elira,
    "nera": ask_nera,
}

async def ask_guide(
    guide_key: str,
    message: str,
    history=None,
) -> str:
    func = ASK_FUNCS.get(guide_key)
    if not func:
        return "Я рядом 🤍 Давай выберем проводника заново."

    return await func(message, history)
