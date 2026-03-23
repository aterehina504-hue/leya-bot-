import sqlite3
import time

DB_PATH = "bot.db"


# ======================
# BASE
# ======================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ======================
# INIT
# ======================
def init_db():
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER,
            guide_key TEXT,
            expires_at INTEGER,
            last_activity_at INTEGER,
            current_day INTEGER DEFAULT 1,
            path_started_at INTEGER,
            recurring_active INTEGER DEFAULT 0,
            recurring_charge_id TEXT,
            recurring_expires_at INTEGER,
            PRIMARY KEY (user_id, guide_key)
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            guide_key TEXT,
            tariff_key TEXT,
            amount INTEGER,
            currency TEXT,
            created_at INTEGER,
            is_recurring INTEGER,
            tg_charge_id TEXT,
            subscription_expiration_date INTEGER,
            ab_group TEXT
        )
        """)


# ======================
# SUBSCRIPTIONS
# ======================
def get_expires(user_id: int, guide_key: str):
    with db() as conn:
        row = conn.execute("""
            SELECT expires_at FROM subscriptions
            WHERE user_id=? AND guide_key=?
        """, (user_id, guide_key)).fetchone()

        return row["expires_at"] if row else None


def set_expires(user_id: int, guide_key: str, expires_at: int):
    with db() as conn:
        conn.execute("""
            INSERT INTO subscriptions (user_id, guide_key, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guide_key)
            DO UPDATE SET expires_at=excluded.expires_at
        """, (user_id, guide_key, expires_at))


def add_days(user_id: int, guide_key: str, days: int):
    now = int(time.time())

    current = get_expires(user_id, guide_key)

    if not current or current < now:
        current = now

    new_exp = current + days * 86400
    set_expires(user_id, guide_key, new_exp)

    return new_exp


def has_subscription(user_id: int, guide_key: str):
    exp = get_expires(user_id, guide_key)
    return bool(exp and exp > time.time())


# ======================
# USER PATH (дни)
# ======================
def update_activity(user_id, guide_key):
    with db() as conn:
        conn.execute("""
            UPDATE subscriptions
            SET last_activity_at=?
            WHERE user_id=? AND guide_key=?
        """, (int(time.time()), user_id, guide_key))


def start_user_path(user_id, guide_key):
    now = int(time.time())

    with db() as conn:
        conn.execute("""
            INSERT INTO subscriptions (user_id, guide_key, path_started_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, guide_key)
            DO UPDATE SET path_started_at=excluded.path_started_at
        """, (user_id, guide_key, now))


def get_user_day(user_id, guide_key):
    with db() as conn:
        row = conn.execute("""
            SELECT path_started_at FROM subscriptions
            WHERE user_id=? AND guide_key=?
        """, (user_id, guide_key)).fetchone()

        if not row or not row["path_started_at"]:
            return 1

        days = int((time.time() - row["path_started_at"]) / 86400) + 1
        return min(days, 7)


# ======================
# PAYMENTS
# ======================
def save_payment(
    user_id,
    guide_key,
    tariff_key,
    amount,
    currency,
    tg_charge_id,
    is_recurring=False,
    is_first_recurring=False,
    subscription_expiration_date=None,
    ab_group=None
):
    with db() as conn:
        conn.execute("""
            INSERT INTO payments (
                user_id, guide_key, tariff_key, amount, currency,
                created_at, is_recurring, tg_charge_id,
                subscription_expiration_date, ab_group
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            guide_key,
            tariff_key,
            amount,
            currency,
            int(time.time()),
            int(is_recurring),
            tg_charge_id,
            subscription_expiration_date,
            ab_group
        ))


def get_revenue_stats():
    with db() as conn:
        total = conn.execute("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(amount),0) as total
            FROM payments
        """).fetchone()

        by_tariff = conn.execute("""
            SELECT guide_key, tariff_key, COUNT(*) as cnt, SUM(amount) as amount
            FROM payments
            GROUP BY guide_key, tariff_key
            ORDER BY amount DESC
        """).fetchall()

        by_ab = conn.execute("""
            SELECT guide_key, ab_group, COUNT(*) as cnt, SUM(amount) as amount
            FROM payments
            WHERE ab_group IS NOT NULL
            GROUP BY guide_key, ab_group
        """).fetchall()

        return total, by_tariff, by_ab


# ======================
# USERS
# ======================
def get_all_active_users():
    with db() as conn:
        rows = conn.execute("""
            SELECT DISTINCT user_id FROM subscriptions
            WHERE expires_at > ?
        """, (int(time.time()),)).fetchall()

        return [r["user_id"] for r in rows]


# ======================
# REMINDERS
# ======================
def get_users_for_reminder(seconds_before):
    now = int(time.time())

    with db() as conn:
        rows = conn.execute("""
            SELECT user_id, guide_key, expires_at, recurring_active
            FROM subscriptions
            WHERE expires_at BETWEEN ? AND ?
        """, (now, now + seconds_before)).fetchall()

        return rows


def mark_reminded(user_id, guide_key):
    # можно расширить потом (лог отправок)
    pass


# ======================
# RECURRING
# ======================
def set_subscription_from_recurring(user_id, guide_key, expires_at, charge_id, active=True):
    with db() as conn:
        conn.execute("""
            INSERT INTO subscriptions (
                user_id, guide_key, expires_at,
                recurring_active, recurring_charge_id, recurring_expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guide_key)
            DO UPDATE SET
                expires_at=excluded.expires_at,
                recurring_active=excluded.recurring_active,
                recurring_charge_id=excluded.recurring_charge_id,
                recurring_expires_at=excluded.recurring_expires_at
        """, (
            user_id,
            guide_key,
            expires_at,
            int(active),
            charge_id,
            expires_at
        ))


def get_recurring_info(user_id, guide_key):
    with db() as conn:
        row = conn.execute("""
            SELECT recurring_active, recurring_charge_id, recurring_expires_at
            FROM subscriptions
            WHERE user_id=? AND guide_key=?
        """, (user_id, guide_key)).fetchone()

        return row


def set_recurring_status(user_id, guide_key, active: bool):
    with db() as conn:
        conn.execute("""
            UPDATE subscriptions
            SET recurring_active=?
            WHERE user_id=? AND guide_key=?
        """, (int(active), user_id, guide_key))


# ======================
# A/B TEST
# ======================
def get_ab_group(user_id: int, guide_key: str):
    # простое детерминированное распределение
    return "A" if (user_id + hash(guide_key)) % 2 == 0 else "B"
