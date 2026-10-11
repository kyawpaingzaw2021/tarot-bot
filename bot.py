#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tarot Bot — Channel-focused (private + group)."""

import logging
import os

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

from config import (
    BOT_TOKEN, CHANNEL_ID, CHANNEL_USERNAME,
    CARDS_DIR, IMAGES_DIR, DAILY_LIMIT,
    has_channel, channel_chat_id,
)
from database import (
    init_db, get_or_create_user, count_today_readings,
    add_reading, update_reading_channel_msg,
)
from cards import load_cards, draw_card, get_orientation, format_reading

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tarot_bot")


# ─── UI Constants ─────────────────────────────────

BTN_DRAW = "🔮 ကတ်ဆွဲမယ်"
BTN_LIMIT = "📊 ကျွန်တော့် limit"
BTN_CHANNEL = "📖 Channel သွား"

CATEGORIES = {
    "love": "❤️ အချစ်ရေး",
    "career": "💼 အလုပ်",
    "money": "💰 ငွေရေး",
    "health": "🏥 ကျန်းမာရေး",
    "family": "👨‍👩‍👧 မိသားစု",
    "study": "📚 ပညာရေး",
    "marriage": "💍 အိမ်ထောင်ရေး",
    "business": "🏢 စီးပွားရေး",
    "travel": "✈️ ခရီးသွား",
    "friendship": "👥 ခင်မင်ရေး",
    "spiritual": "🧘 ဝိညာဉ်ရေး",
    "decision": "🎯 ဆုံးဖြတ်ချက်",
}

TIMEFRAMES = {
    "present": "🕐 လက်ရှိ",
    "future": "🔮 အနာဂတ်",
}

ORIENTATIONS = {
    "upright": "Upright ⬆️",
    "reversed": "Reversed ⬇️",
}


# ─── Helpers ──────────────────────────────────────

def is_group(update_or_query):
    chat = update_or_query.effective_chat
    return chat.type in ("group", "supergroup")


def user_label(user):
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"User {user.id}"


# ─── Keyboards ────────────────────────────────────

def main_menu_reply():
    """Private chat အတွက် — Reply keyboard."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_DRAW)],
            [KeyboardButton(BTN_LIMIT), KeyboardButton(BTN_CHANNEL)],
        ],
        resize_keyboard=True,
    )


def main_menu_inline():
    """Group chat အတွက် — Inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_DRAW, callback_data="menu:draw")],
        [
            InlineKeyboardButton(BTN_LIMIT, callback_data="menu:limit"),
            InlineKeyboardButton(BTN_CHANNEL, callback_data="menu:channel"),
        ],
    ])


def categories_keyboard():
    items = list(CATEGORIES.items())
    rows = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(label, callback_data=f"cat:{key}")
            for key, label in items[i:i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def timeframe_keyboard(category):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🕐 လက်ရှိ", callback_data=f"tf:{category}:present"),
            InlineKeyboardButton("🔮 အနာဂတ်", callback_data=f"tf:{category}:future"),
        ],
        [InlineKeyboardButton("⬅️ ပြန်", callback_data="menu:draw")],
    ])


# ─── Channel URL ──────────────────────────────────

def _channel_main_url():
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}"
    cid = str(CHANNEL_ID)
    if cid.startswith("-100"):
        cid = cid[4:]
    return f"https://t.me/c/{cid}"


def _channel_msg_url(msg_id):
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{msg_id}"
    cid = str(CHANNEL_ID)
    if cid.startswith("-100"):
        cid = cid[4:]
    return f"https://t.me/c/{cid}/{msg_id}"


# ─── Safe Wrappers ────────────────────────────────

async def safe_edit(query, text, keyboard=None, parse_mode=None):
    msg = query.message
    is_media = bool(getattr(msg, "photo", None) or
                    getattr(msg, "document", None) or
                    getattr(msg, "video", None))
    try:
        if is_media:
            await msg.reply_text(text, reply_markup=keyboard, parse_mode=parse_mode)
            try:
                await msg.delete()
            except TelegramError:
                pass
            return None
        return await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=parse_mode,
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return None
        logger.warning("safe_edit BadRequest: %s", e)
        try:
            return await msg.reply_text(text, reply_markup=keyboard, parse_mode=parse_mode)
        except TelegramError:
            return None
    except TelegramError as e:
        logger.error("safe_edit error: %s", e)
        return None


async def safe_reply(message, text, keyboard=None, parse_mode=None):
    try:
        return await message.reply_text(
            text, reply_markup=keyboard, parse_mode=parse_mode,
        )
    except Forbidden:
        logger.warning("User blocked: %s", message.chat_id)
    except TelegramError as e:
        logger.error("safe_reply: %s", e)
    return None


async def safe_send(bot, chat_id, text, keyboard=None, parse_mode=None,
                    disable_preview=False):
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=keyboard,
            parse_mode=parse_mode, disable_web_page_preview=disable_preview,
        )
    except Forbidden:
        logger.warning("Blocked: %s", chat_id)
    except TelegramError as e:
        logger.error("safe_send: %s", e)
    return None


# ─── Commands ─────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    text = (
        f"မင်္ဂလာပါ {user.first_name}! 🔮\n\n"
        f"Tarot Bot မှ ကြိုဆိုပါတယ်။\n"
        f"ကတ်ဆွဲပြီး ဟောချက်ကို channel မှာ ဖတ်ပါ။\n\n"
        f"📊 တစ်နေ့ {DAILY_LIMIT} ကြိမ်\n\n"
        f"⚠️ ဒါက entertainment အတွက်ပါ။"
    )

    if is_group(update):
        await safe_reply(update.message, text, keyboard=main_menu_inline())
    else:
        await safe_reply(update.message, text, keyboard=main_menu_reply())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔮 Tarot Bot — အကူအညီ\n\n"
        f"• {BTN_DRAW} — ကတ်ဆွဲ\n"
        f"• {BTN_LIMIT} — ကျန်တဲ့ အကြိမ်\n"
        f"• {BTN_CHANNEL} — channel ဖွင့်\n\n"
        f"တစ်နေ့ {DAILY_LIMIT} ကြိမ်\n\n"
        f"⚠️ ဟောချက်များကို channel မှာ ဖတ်ပါ။"
    )
    if is_group(update):
        await safe_reply(update.message, text, keyboard=main_menu_inline())
    else:
        await safe_reply(update.message, text, keyboard=main_menu_reply())


# ─── Menu actions ─────────────────────────────────

async def show_categories(update_or_query, context, edit=False):
    text = "📂 ဘယ်အကြောင်းအရာ မေးချင်လဲ?"
    kb = categories_keyboard()
    if edit:
        await safe_edit(update_or_query, text, keyboard=kb)
    else:
        await safe_reply(update_or_query.message, text, keyboard=kb)


async def show_limit(update_or_query, context, edit=False):
    user_id = update_or_query.from_user.id if edit else update_or_query.effective_user.id
    count = count_today_readings(user_id)
    remaining = max(0, DAILY_LIMIT - count)
    text = (
        f"📊 ဒီနေ့ limit\n\n"
        f"• သုံးပြီး: {count}\n"
        f"• ကျန်: {remaining}\n"
        f"• စုစုပေါင်း: {DAILY_LIMIT}\n\n"
        f"မနက် ၀၀:၀၀ (မြန်မာအချိန်) reset"
    )
    if edit:
        await safe_edit(update_or_query, text)
    else:
        kb = main_menu_inline() if is_group(update_or_query) else main_menu_reply()
        await safe_reply(update_or_query.message, text, keyboard=kb)


async def show_channel(update_or_query, context, edit=False):
    if not has_channel():
        msg = "⚠️ Channel မသတ်မှတ်ရသေးပါ။"
        if edit:
            await safe_edit(update_or_query, msg)
        else:
            await safe_reply(update_or_query.message, msg)
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Channel ဖွင့်", url=_channel_main_url())],
    ])
    text = "ဟောချက်အားလုံးကို channel မှာ ဖတ်နိုင်ပါတယ်။"
    if edit:
        await safe_edit(update_or_query, text, keyboard=kb)
    else:
        await safe_reply(update_or_query.message, text, keyboard=kb)


# ─── Text Handler ─────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply keyboard buttons — Private chat အတွက်ပဲ."""
    # Group မှာ ဘာမှ မလုပ်ဘူး (commands ပဲ respond)
    if is_group(update):
        return

    text = (update.message.text or "").strip()
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    if text == BTN_DRAW:
        await show_categories(update, context)
    elif text == BTN_LIMIT:
        await show_limit(update, context)
    elif text == BTN_CHANNEL:
        await show_channel(update, context)
    else:
        # Unknown text — private မှာ menu ပြ
        await safe_reply(
            update.message, "Menu ကို သုံးပါ 👇",
            keyboard=main_menu_reply(),
        )


# ─── Callback Handler ─────────────────────────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    parts = data.split(":")
    action = parts[0] if parts else ""

    try:
        await query.answer()
    except TelegramError:
        pass

    if action == "menu":
        sub = parts[1] if len(parts) > 1 else "home"
        if sub == "draw":
            await show_categories(query, context, edit=True)
        elif sub == "limit":
            await show_limit(query, context, edit=True)
        elif sub == "channel":
            await show_channel(query, context, edit=True)
        return

    if action == "cat":
        if len(parts) < 2 or parts[1] not in CATEGORIES:
            await safe_edit(query, "⚠️ Category မမှန်ပါ။")
            return
        category = parts[1]
        await safe_edit(
            query,
            f"{CATEGORIES[category]}\n\nဘယ်အချိန်အတွက် မေးချင်လဲ?",
            keyboard=timeframe_keyboard(category),
        )
        return

    if action == "tf":
        if len(parts) < 3:
            await safe_edit(query, "⚠️ Data မမှန်ပါ။")
            return
        category, timeframe = parts[1], parts[2]
        if category not in CATEGORIES or timeframe not in TIMEFRAMES:
            await safe_edit(query, "⚠️ Data မမှန်ပါ။")
            return
        await process_reading(query, context, category, timeframe)
        return


# ─── Reading Flow ─────────────────────────────────

async def process_reading(query, context, category, timeframe):
    user = query.from_user
    chat = query.message.chat
    is_group_chat = chat.type in ("group", "supergroup")

    # Register user
    get_or_create_user(user.id, user.username, user.first_name)

    # Limit check
    count = count_today_readings(user.id)
    if count >= DAILY_LIMIT:
        await safe_edit(
            query,
            f"⚠️ ဒီနေ့ limit ({DAILY_LIMIT} ကြိမ်) ကုန်ပါပြီ။\n"
            f"မနက် ၀၀:၀၀ မှာ reset ဖြစ်ပါမယ်။\n\n"
            f"📖 Channel မှာ ဟောင်းတွေ ဖတ်ပါ။",
        )
        return

    # Loading
    await safe_edit(query, "⏳ ကတ်ဆွဲနေတယ်...")

    cards = context.bot_data.get("cards") or []
    if not cards:
        await safe_edit(query, "❌ ကတ် data မရှိပါ။")
        return

    card = draw_card(cards)
    orientation = get_orientation()

    # Save reading (with chat info)
    reading_id = add_reading(
        user.id, card.get("id", ""), category, timeframe, orientation,
        None, chat.id, chat.type,
    )

    # Format for channel
    text = format_reading(
        card, category, timeframe, orientation, reading_id,
        CATEGORIES, TIMEFRAMES, ORIENTATIONS,
    )

    # Post to channel
    chat_id_channel = channel_chat_id()
    if not chat_id_channel:
        await safe_edit(query, "❌ Channel မသတ်မှတ်ရသေးပါ။")
        return

    try:
        channel_msg = await context.bot.send_message(
            chat_id=chat_id_channel,
            text=text,
            disable_web_page_preview=True,
        )
        update_reading_channel_msg(reading_id, channel_msg.message_id)
        link = _channel_msg_url(channel_msg.message_id)
    except TelegramError:
        logger.exception("Channel ပို့လို့မရ")
        await safe_edit(query, "❌ Channel မှာ ပို့လို့ မရပါ။ Bot ကို channel admin လုပ်ပါ။")
        return

    # Compose caption
    remaining = max(0, DAILY_LIMIT - count - 1)
    card_name = card.get("name", "?")

    if is_group_chat:
        # Group — card only, no reading
        caption = (
            f"🎴 {card_name}\n"
            f"{CATEGORIES[category]} | {TIMEFRAMES[timeframe]} | {ORIENTATIONS[orientation]}\n\n"
            f"👤 {user_label(user)}\n\n"
            f"📖 ဟောချက်ကို channel မှာ ဖတ်ပါ။\n"
            f"📊 {user_label(user)} ကျန်: {remaining}/{DAILY_LIMIT}"
        )
        target_chat_id = chat.id
    else:
        # Private
        caption = (
            f"🎴 {card_name}\n"
            f"{CATEGORIES[category]} | {TIMEFRAMES[timeframe]} | {ORIENTATIONS[orientation]}\n\n"
            f"📖 ဟောချက်ကို channel မှာ ဖတ်ပါ။\n\n"
            f"📊 ကျန်: {remaining}/{DAILY_LIMIT}"
        )
        target_chat_id = user.id

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 ဟောချက် ဖတ်မယ်", url=link)],
        [InlineKeyboardButton("🔄 နောက်တစ်ကတ်", callback_data="menu:draw")],
    ])

    # Delete loading
    try:
        await query.message.delete()
    except TelegramError:
        pass

    # Image
    image_path = None
    img_name = card.get("image")
    if img_name and os.path.isdir(IMAGES_DIR):
        p = os.path.join(IMAGES_DIR, img_name)
        if os.path.exists(p):
            image_path = p

    # Send
    sent = False
    if image_path:
        try:
            with open(image_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=target_chat_id, photo=f,
                    caption=caption, reply_markup=keyboard,
                )
            sent = True
        except TelegramError as e:
            logger.warning("Photo ပို့လို့မရ: %s", e)

    if not sent:
        await safe_send(context.bot, target_chat_id, caption, keyboard=keyboard)


# ─── Error Handler ────────────────────────────────

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s — Error %s", update, context.error, exc_info=context.error)


# ─── Main ─────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN မရှိပါ။ .env ထဲ ထည့်ပါ။")
        return
    if not has_channel():
        print("❌ CHANNEL_ID သို့မဟုတ် CHANNEL_USERNAME ထည့်ပါ။")
        return

    init_db()

    cards = load_cards(CARDS_DIR)
    if not cards:
        print(f"❌ Cards မတွေ့ပါ: {CARDS_DIR}")
        return
    print(f"✅ Cards {len(cards)} ကတ်")

    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["cards"] = cards

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)

    print("🚀 Bot စတင်နေပါပြီ...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
