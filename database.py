import sqlite3
from datetime import datetime, timezone, timedelta

from config import DB_PATH

MMT = timezone(timedelta(hours=6, minutes=30))


def now_mmt():
    return datetime.now(MMT)


def today_mmt_str():
    return now_mmt().strftime("%Y-%m-%d")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def init_db():
    conn = _conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_id TEXT,
            category TEXT,
            timeframe TEXT,
            orientation TEXT,
            channel_msg_id INTEGER,
            chat_id INTEGER,
            chat_type TEXT,
            created_at TEXT
        )
    """)

    # Migration: old DB ဆိုရင် column ထည့်
    if not _column_exists(c, "readings", "chat_id"):
        c.execute("ALTER TABLE readings ADD COLUMN chat_id INTEGER")
    if not _column_exists(c, "readings", "chat_type"):
        c.execute("ALTER TABLE readings ADD COLUMN chat_type TEXT")

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_readings_user_date
        ON readings(user_id, created_at)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_readings_date
        ON readings(created_at)
    """)

    conn.commit()
    conn.close()


def get_or_create_user(user_id, username, first_name):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """INSERT OR IGNORE INTO users
           (user_id, username, first_name, created_at)
           VALUES (?, ?, ?, ?)""",
        (user_id, username or "", first_name or "", now_mmt().isoformat()),
    )
    c.execute(
        "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
        (username or "", first_name or "", user_id),
    )
    conn.commit()
    conn.close()


def count_today_readings(user_id):
    """User တစ်ယောက်ရဲ့ ဒီနေ့ reading အရေအတွက် (private + group စုစုပေါင်း)."""
    today = today_mmt_str()
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """SELECT COUNT(*) FROM readings
           WHERE user_id = ? AND substr(created_at, 1, 10) = ?""",
        (user_id, today),
    )
    count = c.fetchone()[0]
    conn.close()
    return count


def add_reading(user_id, card_id, category, timeframe, orientation,
                channel_msg_id=None, chat_id=None, chat_type=None):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO readings
           (user_id, card_id, category, timeframe, orientation,
            channel_msg_id, chat_id, chat_type, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, card_id, category, timeframe, orientation,
         channel_msg_id, chat_id, chat_type, now_mmt().isoformat()),
    )
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_reading_channel_msg(reading_id, channel_msg_id):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        "UPDATE readings SET channel_msg_id = ? WHERE id = ?",
        (channel_msg_id, reading_id),
    )
    conn.commit()
    conn.close()


def get_user_readings(user_id, limit=10):
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """SELECT * FROM readings WHERE user_id = ?
           ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows
