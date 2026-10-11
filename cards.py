import glob
import json
import os
import random

from config import CARDS_DIR, REVERSAL_CHANCE


def load_cards(cards_dir=None):
    cards_dir = cards_dir or CARDS_DIR
    cards = []
    errors = []
    if not os.path.isdir(cards_dir):
        print(f"⚠️  Cards directory မရှိ: {cards_dir}")
        return cards

    for path in sorted(glob.glob(os.path.join(cards_dir, "*.json"))):
        name = os.path.basename(path)
        if name == "index.json":
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "id" not in data or "name" not in data:
                errors.append(name + " (missing id/name)")
                continue
            cards.append(data)
        except json.JSONDecodeError as e:
            errors.append(f"{name} (JSON error: {e})")
        except Exception as e:
            errors.append(f"{name} ({type(e).__name__}: {e})")

    if errors:
        print(f"⚠️  {len(errors)} ဖိုင် ဖတ်လို့မရ:")
        for e in errors[:5]:
            print(f"   - {e}")
    return cards


def draw_card(cards):
    if not cards:
        return None
    return random.choice(cards)


def get_orientation(reversal_chance=None):
    chance = REVERSAL_CHANCE if reversal_chance is None else reversal_chance
    return "reversed" if random.random() < chance else "upright"


def _safe_get(d, keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def format_reading(card, category, timeframe, orientation, reading_id,
                   category_names, timeframe_names, orientation_names):
    """Format reading for channel posting. Handles new 5-part dict and old string."""
    data = _safe_get(card, ["readings", category, timeframe, orientation], None)

    lines = [
        f"🎴 {card.get('name', 'Unknown')}",
        f"{category_names.get(category, category)} | "
        f"{timeframe_names.get(timeframe, timeframe)} | "
        f"{orientation_names.get(orientation, orientation)}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    parts_added = 0

    if isinstance(data, str) and data.strip():
        lines.append(data.strip())
        parts_added = 1
    elif isinstance(data, dict):
        parts = [
            ("📍 အခြေအနေ", "situation"),
            ("💡 အကြောင်းရင်း", "reason"),
            ("🎯 အဓိပ္ပာယ်", "meaning"),
            ("✅ လုပ်ဆောင်ရမယ့်အရာ", "action"),
            ("⚠️ အနာဂတ်", "outcome"),
        ]
        for label, key in parts:
            val = (data.get(key) or "").strip()
            if val:
                lines.append(f"{label}\n{val}")
                lines.append("")
                parts_added += 1

    if parts_added == 0:
        lines.append("(ဟောချက် မရှိသေးပါ — ပြင်ဆင်နေတယ်)")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"#reading_{reading_id}")
    return "\n".join(lines)
