import sqlite3
import time

DB_PATH = "bot.db"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
            last_retention_type TEXT,
            PRIMARY KEY (user_id, guide_key)
        )
        """)

def update_activity(user_id, guide_key):
    with db() as conn:
        conn.execute("""
        UPDATE subscriptions
        SET last_activity_at = ?
        WHERE user_id=? AND guide_key=?
        """, (int(time.time()), user_id, guide_key))

def start_user_path(user_id, guide_key):
    now = int(time.time())
    with db() as conn:
        conn.execute("""
        UPDATE subscriptions
        SET current_day=1, path_started_at=?
        WHERE user_id=? AND guide_key=?
        """, (now, user_id, guide_key))

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
