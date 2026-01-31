import sqlite3
import time
import json
from typing import Optional, List, Tuple

DB_PATH = "db.sqlite3"


# ======================
# INIT
# ======================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            guide TEXT,
            expires INTEGER,
            last_message INTEGER,
            flags TEXT
        )
    """)

    conn.commit()
    conn.close()


# ======================
# ACCESS
# ======================
def get_expires(user_id: int, guide: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT expires FROM users WHERE user_id=? AND guide=?",
        (user_id, guide)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row and row[0] else 0


def add_days(user_id: int, guide: str, days: int):
    now = int(time.time())
    current = get_expires(user_id, guide)

    expires = now + days * 86400 if current < now else current + days * 86400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (user_id, guide, expires, last_message, flags)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            guide=excluded.guide,
            expires=excluded.expires
    """, (user_id, guide, expires, now, "{}"))

    conn.commit()
    conn.close()


# ======================
# MESSAGES
# ======================
def set_last_message_time(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "UPDATE users SET last_message=? WHERE user_id=?",
        (int(time.time()), user_id)
    )

    conn.commit()
    conn.close()


def get_last_message_time(user_id: int) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT last_message FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


# ======================
# FLAGS (REMINDERS)
# ======================
def get_flag(user_id: int, flag: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT flags FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    if not row or not row[0]:
        return False

    flags = json.loads(row[0])
    return flags.get(flag, False)


def set_flag(user_id: int, flag: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT flags FROM users WHERE user_id=?",
        (user_id,)
    )
    row = cur.fetchone()

    flags = json.loads(row[0]) if row and row[0] else {}
    flags[flag] = True

    cur.execute(
        "UPDATE users SET flags=? WHERE user_id=?",
        (json.dumps(flags), user_id)
    )

    conn.commit()
    conn.close()


# ======================
# REMINDER WORKER
# ======================
def get_all_active_users() -> List[Tuple[int, str, int]]:
    now = int(time.time())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT user_id, guide, expires
        FROM users
        WHERE expires > ?
    """, (now,))

    rows = cur.fetchall()
    conn.close()

    return rows
