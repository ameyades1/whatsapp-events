"""Thursday teaching post: one message from the bank, which holds
  wa-messages/<slug>_whatsapp_en.txt   YouTube teachings, sent as text so WhatsApp
                                       shows the video preview;
  wa-courses/<slug>.txt + <slug>.jpg   course posts, sent as that image with the
                                       text as its caption (.jpeg/.png also work).

Which message goes out on a date:
  1. teaching-schedule.csv (date, slug, occasion), planned around festivals, if it
     lists that date and the message hasn't been sent yet;
  2. otherwise the next YouTube teaching in a fixed shuffled order, skipping ones
     already sent and ones the schedule reserves for a later date. Course posts
     are never picked this way: they go out only on a date the schedule gives them.
Each send is logged as an "included" row keyed "teaching:<slug>".
"""

import csv

import random
import re
from pathlib import Path

BANK = Path(__file__).parent / "wa-messages"
SUFFIX = "_whatsapp_en.txt"
COURSES = Path(__file__).parent / "wa-courses"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
SCHEDULE = Path(__file__).parent / "teaching-schedule.csv"
SEED = "antaryog-teachings-v1"   # change to reshuffle the order


def load_schedule():
    """{date_iso: (slug, occasion)}"""
    if not SCHEDULE.exists():
        return {}
    with SCHEDULE.open(newline="", encoding="utf-8") as f:
        return {r["date"]: (r["slug"], r.get("occasion", "")) for r in csv.DictReader(f)}


def _item(f, slug, image=None):
    text = f.read_text(encoding="utf-8")
    text = "\n".join(line.rstrip() for line in text.strip().splitlines())
    m = re.match(r"\*(.+?)\*", text)
    return {"key": f"teaching:{slug}", "slug": slug, "image": image,
            "title": m.group(1).strip() if m else slug, "body": text}


def course_image(txt):
    """The image next to a course post (same name), or None."""
    return next((p for p in (txt.with_suffix(e) for e in IMAGE_EXTS) if p.exists()), None)


def load_bank():
    items = [_item(f, f.name[: -len(SUFFIX)]) for f in sorted(BANK.glob(f"*{SUFFIX}"))]

    random.Random(SEED).shuffle(items)
    # Course posts come after, and only go out on dates teaching-schedule.csv gives them.
    for f in sorted(COURSES.glob("*.txt")):
        img = course_image(f)
        if img is None:
            print(f"WARN: {f.name} has no image next to it - skipped")
            continue
        items.append(_item(f, f.stem, img))
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
        if item["image"]:
            continue  # course posts only go out on their scheduled date
        if item["key"] not in sent_keys and item["slug"] not in reserved:
            return dict(item, occasion="")
    return None


def format_post(item):
    return item["body"]
