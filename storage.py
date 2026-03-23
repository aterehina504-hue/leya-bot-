import random
import sqlite3
import time
from typing import Optional, List, Dict

DB_PATH = "bot.db"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ======================
# INIT
# ======================
def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                guide_key TEXT NOT NULL,
                expires_at INTEGER NOT NULL DEFAULT 0,
                reminded_24h INTEGER NOT NULL DEFAULT 0,

                recurring_charge_id TEXT,
                recurring_active INTEGER NOT NULL DEFAULT 0,
                recurring_expires_at INTEGER,

                last_activity_at INTEGER,
                last_retention_type TEXT,

                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,

                PRIMARY KEY (user_id, guide_key)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                guide_key TEXT NOT NULL,
                tariff_key TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                tg_charge_id TEXT NOT NULL UNIQUE,
                is_recurring INTEGER NOT NULL DEFAULT 0,
                is_first_recurring INTEGER NOT NULL DEFAULT 0,
                subscription_expiration_date INTEGER,
                ab_group TEXT,
                paid_at INTEGER NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_ab (
                user_id INTEGER NOT NULL,
                guide_key TEXT NOT NULL,
                ab_group TEXT NOT NULL,
                assigned_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, guide_key)
            )
            """
        )


# ======================
# ACTIVITY
# ======================
def update_activity(user_id: int, guide_key: str):
    now = int(time.time())
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET last_activity_at = ?, updated_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (now, now, user_id, guide_key),
        )


# ======================
# AB TEST
# ======================
def get_ab_group(user_id: int, guide_key: str) -> str:
    with db() as conn:
        row = conn.execute(
            "SELECT ab_group FROM user_ab WHERE user_id = ? AND guide_key = ?",
            (user_id, guide_key),
        ).fetchone()

        if row:
            return row["ab_group"]

        ab_group = random.choice(["A", "B"])
        conn.execute(
            "INSERT INTO user_ab (user_id, guide_key, ab_group, assigned_at) VALUES (?, ?, ?, ?)",
            (user_id, guide_key, ab_group, int(time.time())),
        )
        return ab_group


# ======================
# SUBSCRIPTIONS
# ======================
def get_expires(user_id: int, guide_key: str) -> Optional[int]:
    with db() as conn:
        row = conn.execute(
            "SELECT expires_at FROM subscriptions WHERE user_id = ? AND guide_key = ?",
            (user_id, guide_key),
        ).fetchone()
        return row["expires_at"] if row else None


def has_subscription(user_id: int, guide_key: str) -> bool:
    exp = get_expires(user_id, guide_key)
    return bool(exp and exp > time.time())


def add_days(user_id: int, guide_key: str, days: int) -> int:
    now = int(time.time())
    current = get_expires(user_id, guide_key) or 0

    if current > now:
        new_exp = current + days * 86400
    else:
        new_exp = now + days * 86400

    with db() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (
                user_id, guide_key, expires_at,
                reminded_24h,
                last_activity_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(user_id, guide_key) DO UPDATE SET
                expires_at = excluded.expires_at,
                reminded_24h = 0,
                last_activity_at = excluded.last_activity_at,
                updated_at = excluded.updated_at
            """,
            (user_id, guide_key, new_exp, now, now, now),
        )

    return new_exp


# ======================
# RECURRING
# ======================
def set_subscription_from_recurring(user_id: int, guide_key: str, expires_at: int, charge_id: str, active: bool):
    now = int(time.time())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions (
                user_id, guide_key, expires_at,
                recurring_charge_id, recurring_active, recurring_expires_at,
                last_activity_at,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guide_key) DO UPDATE SET
                expires_at = excluded.expires_at,
                recurring_charge_id = excluded.recurring_charge_id,
                recurring_active = excluded.recurring_active,
                recurring_expires_at = excluded.recurring_expires_at,
                last_activity_at = excluded.last_activity_at,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                guide_key,
                expires_at,
                charge_id,
                1 if active else 0,
                expires_at,
                now,
                now,
                now,
            ),
        )


def get_recurring_info(user_id: int, guide_key: str):
    with db() as conn:
        return conn.execute(
            """
            SELECT recurring_charge_id, recurring_active, recurring_expires_at
            FROM subscriptions
            WHERE user_id = ? AND guide_key = ?
            """,
            (user_id, guide_key),
        ).fetchone()


def set_recurring_status(user_id: int, guide_key: str, active: bool):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET recurring_active = ?, updated_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (1 if active else 0, int(time.time()), user_id, guide_key),
        )


# ======================
# PAYMENTS
# ======================
def save_payment(
    user_id: int,
    guide_key: str,
    tariff_key: str,
    amount: int,
    currency: str,
    tg_charge_id: str,
    is_recurring: bool,
    is_first_recurring: bool,
    subscription_expiration_date,
    ab_group: str | None,
):
    with db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO payments (
                user_id, guide_key, tariff_key, amount, currency,
                tg_charge_id, is_recurring, is_first_recurring,
                subscription_expiration_date, ab_group, paid_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                guide_key,
                tariff_key,
                amount,
                currency,
                tg_charge_id,
                1 if is_recurring else 0,
                1 if is_first_recurring else 0,
                subscription_expiration_date,
                ab_group,
                int(time.time()),
            ),
        )


# ======================
# RETENTION QUERIES
# ======================

def get_users_for_inactive(days: int) -> List[Dict]:
    now = int(time.time())
    threshold = now - days * 86400

    with db() as conn:
        return conn.execute(
            """
            SELECT user_id, guide_key, last_activity_at, last_retention_type
            FROM subscriptions
            WHERE last_activity_at IS NOT NULL
              AND last_activity_at <= ?
            """,
            (threshold,),
        ).fetchall()


def get_users_for_expired(days: int) -> List[Dict]:
    now = int(time.time())
    threshold = now - days * 86400

    with db() as conn:
        return conn.execute(
            """
            SELECT user_id, guide_key, expires_at, last_retention_type
            FROM subscriptions
            WHERE expires_at <= ?
            """,
            (threshold,),
        ).fetchall()


def set_retention_sent(user_id: int, guide_key: str, retention_type: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET last_retention_type = ?, updated_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (retention_type, int(time.time()), user_id, guide_key),
        )


# ======================
# REMINDER (старый)
# ======================
def get_users_for_reminder(reminder_before_seconds: int):
    now = int(time.time())
    limit_ts = now + reminder_before_seconds

    with db() as conn:
        return conn.execute(
            """
            SELECT user_id, guide_key, expires_at, recurring_active
            FROM subscriptions
            WHERE expires_at > ?
              AND expires_at <= ?
              AND reminded_24h = 0
            """,
            (now, limit_ts),
        ).fetchall()


def mark_reminded(user_id: int, guide_key: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET reminded_24h = 1, updated_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (int(time.time()), user_id, guide_key),
        )


# ======================
# STATS
# ======================
def get_all_active_users():
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM subscriptions WHERE expires_at > ?",
            (int(time.time()),),
        ).fetchall()
        return [r["user_id"] for r in rows]


def get_revenue_stats():
    with db() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt FROM payments"
        ).fetchone()

        by_tariff = conn.execute(
            """
            SELECT guide_key, tariff_key, COALESCE(SUM(amount),0) AS amount, COUNT(*) AS cnt
            FROM payments
            GROUP BY guide_key, tariff_key
            ORDER BY amount DESC
            """
        ).fetchall()

        by_ab = conn.execute(
            """
            SELECT guide_key, ab_group, COALESCE(SUM(amount),0) AS amount, COUNT(*) AS cnt
            FROM payments
            WHERE ab_group IS NOT NULL
            GROUP BY guide_key, ab_group
            """
        ).fetchall()

        return total, by_tariff, by_ab

current_day INTEGER DEFAULT 1
path_started_at INTEGER

def start_user_path(user_id: int, guide_key: str):
    now = int(time.time())
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET current_day = 1,
                path_started_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (now, user_id, guide_key),
        )


def get_user_day(user_id: int, guide_key: str) -> int:
    with db() as conn:
        row = conn.execute(
            """
            SELECT current_day, path_started_at
            FROM subscriptions
            WHERE user_id = ? AND guide_key = ?
            """,
            (user_id, guide_key),
        ).fetchone()

        if not row:
            return 1

        if not row["path_started_at"]:
            return row["current_day"] or 1

        days_passed = int((time.time() - row["path_started_at"]) / 86400) + 1
        return min(days_passed, 7)


def advance_day(user_id: int, guide_key: str):
    with db() as conn:
        conn.execute(
            """
            UPDATE subscriptions
            SET current_day = MIN(current_day + 1, 7),
                updated_at = ?
            WHERE user_id = ? AND guide_key = ?
            """,
            (int(time.time()), user_id, guide_key),
        )
        
PATH_STEPS = {
    "leya": {
        1: "Давай немного замедлимся.\n\nЧто сейчас больше всего тебя тревожит?",
        2: "Попробуй описать это чувство точнее.\n\nЧто ты сейчас испытываешь?",
        3: "В каких ситуациях ты чаще всего теряешь себя?",
        4: "Как будто внутри есть конфликт.\n\nМежду чем и чем он?",
        5: "А если выбрать себя — что это было бы?",
        6: "Что ты уже начала замечать в себе за эти дни?",
        7: "Ты прошла важный путь.\n\nЧто изменилось внутри?",
    },

    "amira": {
        1: "Где ты сейчас ставишь себя не на первое место?",
        2: "В каких моментах ты соглашаешься, хотя не хочешь?",
        3: "Что ты боишься потерять, если начнёшь выбирать себя?",
        4: "Где ты терпишь лишнее?",
        5: "А если бы ты уважала себя полностью — что изменилось бы?",
        6: "Что уже стало иначе?",
        7: "Какой ты хочешь быть дальше?",
    },
}

def build_progress_text(day: int) -> str:
    return (
        f"День {day} из 7\n\n"
        f"Ты уже в процессе.\n"
        f"И это важно 🤍"
    )
