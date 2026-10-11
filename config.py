import os
from dotenv import load_dotenv

load_dotenv()


def _clean(v):
    return (v or "").strip()


BOT_TOKEN = _clean(os.getenv("BOT_TOKEN"))

_raw_id = _clean(os.getenv("CHANNEL_ID"))
CHANNEL_ID = None
if _raw_id:
    try:
        CHANNEL_ID = int(_raw_id)
    except ValueError:
        CHANNEL_ID = _raw_id

_raw_user = _clean(os.getenv("CHANNEL_USERNAME"))
if _raw_user.startswith("@"):
    _raw_user = _raw_user[1:]
CHANNEL_USERNAME = _raw_user or ""

# ── Paths — Project folder အတွင်း ──
HOME = os.path.expanduser("~")
PROJECT_DIR = os.path.join(HOME, "tarot_bot")
CARDS_DIR = os.path.join(PROJECT_DIR, "data", "cards")
IMAGES_DIR = os.path.join(PROJECT_DIR, "data", "images")
DB_PATH = os.path.join(PROJECT_DIR, "tarot.db")

# Settings
DAILY_LIMIT = 5
REVERSAL_CHANCE = 0.3


def has_channel():
    return bool(CHANNEL_ID) or bool(CHANNEL_USERNAME)


def channel_chat_id():
    if CHANNEL_ID is not None:
        return CHANNEL_ID
    if CHANNEL_USERNAME:
        return "@" + CHANNEL_USERNAME
    return None
