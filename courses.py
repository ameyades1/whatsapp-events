"""Monthly course post: a course from wa-courses/, sent as its thumbnail with the
text as caption.

  wa-courses/<slug>.txt + <slug>.jpg   (.jpeg/.png also work)
  course-schedule.csv                  date, slug, occasion

The workflow runs every Tuesday; a post goes out only on a date the schedule lists
(normally the first Tuesday of the month, or the Tuesday before an occasion).
Each send is logged as an "included" row keyed "course:<slug>".
"""

import csv
import re
from pathlib import Path

COURSES = Path(__file__).parent / "wa-courses"
SCHEDULE = Path(__file__).parent / "course-schedule.csv"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def load_schedule():
    """{date_iso: (slug, occasion)}"""
    if not SCHEDULE.exists():
        return {}
    with SCHEDULE.open(newline="", encoding="utf-8") as f:
        return {r["date"]: (r["slug"], r.get("occasion", "")) for r in csv.DictReader(f)}


def load_courses():
    """{slug: item}; posts without an image next to them are skipped."""
    items = {}
    for f in sorted(COURSES.glob("*.txt")):
        image = next((p for p in (f.with_suffix(e) for e in IMAGE_EXTS) if p.exists()), None)
        if image is None:
            print(f"WARN: {f.name} has no image next to it - skipped")
            continue
        text = "\n".join(line.rstrip() for line in f.read_text(encoding="utf-8").strip().splitlines())
        m = re.match(r"\*(.+?)\*", text)
        items[f.stem] = {"key": f"course:{f.stem}", "slug": f.stem, "image": image,
                         "title": m.group(1).strip() if m else f.stem, "body": text}
    return items


def pick(sent_keys, d, courses=None, schedule=None):
    """The course scheduled for date d, unless already sent; else None."""
    courses = courses if courses is not None else load_courses()
    schedule = schedule if schedule is not None else load_schedule()
    slug, occasion = schedule.get(d.isoformat(), (None, ""))
    item = courses.get(slug)
    if item and item["key"] not in sent_keys:
        return dict(item, occasion=occasion)
    return None
