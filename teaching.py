"""Thursday teaching post: one message from wa-messages/, sent as text so WhatsApp
shows the YouTube preview.

Which message goes out on a date:
  1. teaching-schedule.csv (date, slug, occasion), planned around festivals, if it
     lists that date and the message hasn't been sent yet;
  2. otherwise the next message in a fixed shuffled order, skipping ones already
     sent and ones the schedule reserves for a later date.
Each send is logged as an "included" row keyed "teaching:<slug>".
"""

import csv

import random
import re
from pathlib import Path

BANK = Path(__file__).parent / "wa-messages"
SUFFIX = "_whatsapp_en.txt"
SCHEDULE = Path(__file__).parent / "teaching-schedule.csv"
SEED = "antaryog-teachings-v1"   # change to reshuffle the order


def load_schedule():
    """{date_iso: (slug, occasion)}"""
    if not SCHEDULE.exists():
        return {}
    with SCHEDULE.open(newline="", encoding="utf-8") as f:
        return {r["date"]: (r["slug"], r.get("occasion", "")) for r in csv.DictReader(f)}


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


def pick(sent_keys, d=None, bank=None, schedule=None):
    """Message for date d (scheduled one if any), or None when nothing is left."""
    bank = bank if bank is not None else load_bank()
    schedule = schedule if schedule is not None else load_schedule()
    by_slug = {x["slug"]: x for x in bank}
    if d is not None and d.isoformat() in schedule:
        slug, occasion = schedule[d.isoformat()]
        item = by_slug.get(slug)
        if item and item["key"] not in sent_keys:
            return dict(item, occasion=occasion)
    reserved = {slug for day, (slug, _) in schedule.items() if d is None or day > d.isoformat()}
    for item in bank:
        if item["key"] not in sent_keys and item["slug"] not in reserved:
            return dict(item, occasion="")
    return None


def format_post(item):
    return item["body"]
