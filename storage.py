import sqlite3
import time
from typing import Optional

DB_PATH = "db.sqlite3"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS access (
    user_id INTEGER PRIMARY KEY,
    leya_expires INTEGER,
    amira_expires INTEGER,
    elira_expires INTEGER,
    nera_expires INTEGER
)
""")

    conn.commit()
    conn.close()

def get_leya_expires(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT leya_expires FROM access WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row and row[0] else 0

def set_leya_expires(user_id: int, expires: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO access (user_id, leya_expires)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET leya_expires=excluded.leya_expires
    """, (user_id, expires))

    conn.commit()
    conn.close()

def add_leya_days(user_id: int, days: int):
    now = int(time.time())
    current = get_leya_expires(user_id)

    if current < now:
        new_expires = now + days * 86400
    else:
        new_expires = current + days * 86400

    set_leya_expires(user_id, new_expires)

def get_amira_expires(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT amira_expires FROM access WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row and row[0] else 0


def add_amira_days(user_id: int, days: int):
    now = int(time.time())
    current = get_amira_expires(user_id)

    if current < now:
        new_expires = now + days * 86400
    else:
        new_expires = current + days * 86400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO access (user_id, amira_expires)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET amira_expires=excluded.amira_expires
    """, (user_id, new_expires))

    conn.commit()
    conn.close()

def get_elira_expires(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT elira_expires FROM access WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row and row[0] else 0


def add_elira_days(user_id: int, days: int):
    now = int(time.time())
    current = get_elira_expires(user_id)

    if current < now:
        new_expires = now + days * 86400
    else:
        new_expires = current + days * 86400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO access (user_id, elira_expires)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET elira_expires=excluded.elira_expires
    """, (user_id, new_expires))

    conn.commit()
    conn.close()

def get_nera_expires(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        "SELECT nera_expires FROM access WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    conn.close()

    return row[0] if row and row[0] else 0


def add_nera_days(user_id: int, days: int):
    now = int(time.time())
    current = get_nera_expires(user_id)

    if current < now:
        new_expires = now + days * 86400
    else:
        new_expires = current + days * 86400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO access (user_id, nera_expires)
    VALUES (?, ?)
    ON CONFLICT(user_id) DO UPDATE SET nera_expires=excluded.nera_expires
    """, (user_id, new_expires))

    conn.commit()
    conn.close()

