"""Thursday teaching post: one message from wa-messages/, sent as text so WhatsApp
shows the YouTube preview.

Messages are taken in a fixed shuffled order (stable, so the plan is predictable
and topics are mixed), skipping any already sent. Each send is logged as an
"included" row keyed "teaching:<slug>".
"""

import random
import re
from pathlib import Path

BANK = Path(__file__).parent / "wa-messages"
SUFFIX = "_whatsapp_en.txt"
HEADER = "*ANTAR YOG FOUNDATION*\n🎥 *Wisdom for the week*"
SEED = "antaryog-teachings-v1"   # change to reshuffle the order


def load_bank():
    items = []
    for f in sorted(BANK.glob(f"*{SUFFIX}")):
        text = f.read_text(encoding="utf-8")
        text = "\n".join(line.rstrip() for line in text.strip().splitlines())
        slug = f.name[: -len(SUFFIX)]
        m = re.match(r"\*(.+?)\*", text)
        items.append({"key": f"teaching:{slug}", "slug": slug,
                      "title": m.group(1).strip() if m else slug, "body": text})
    random.Random(SEED).shuffle(items)
    return items


def pick(sent_keys, bank=None):
    """Next message not yet sent, or None when the bank is used up."""
    for item in bank if bank is not None else load_bank():
        if item["key"] not in sent_keys:
            return item
    return None


def format_post(item):
    return f"{HEADER}\n\n{item['body']}"
