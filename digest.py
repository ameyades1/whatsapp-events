"""Weekly digest: the fixed logo banner (assets/banner.png) + a caption listing the week's events.

Runs once a week (default Monday). The digest covers events starting from the
send day through the following Sunday, plus a "Coming up" line for the next
event after that. Logged in sent-log.csv as kind "digest", keyed by week start.

Env vars: same as announce.py (GREEN_API_*, WA_GROUP_IDS, DRY_RUN), plus
  GREEN_API_MEDIA_URL   host for file uploads (Green-API shows it in the console;
                        defaults to GREEN_API_URL)
  SEND_GAP_SECONDS      pause between groups (default 90)

Usage:
  python digest.py                 send this week's digest
  python digest.py --preview       print this week's caption without sending
"""

import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import announce as a

ROOT = Path(__file__).parent
BANNER = ROOT / "assets" / "banner.png"   # fixed image, made once from the site's logo
CAPTION_LIMIT = 1000          # WhatsApp caption limit is ~1024; keep a margin


# ---------- text ----------

def short_date(ev):
    s = re.sub(r",?\s*20\d\d", "", ev["date_text"])
    for long, short in [("January", "Jan"), ("February", "Feb"), ("March", "Mar"), ("April", "Apr"),
                        ("June", "Jun"), ("July", "Jul"), ("August", "Aug"), ("September", "Sep"),
                        ("October", "Oct"), ("November", "Nov"), ("December", "Dec")]:
        s = s.replace(long, short)
    return s.replace(",", "").replace(" to ", " – ")


def short_mode(ev):
    d = ev["details"]
    m = d.get("Mode") or d.get("Venue") or ""
    if re.search(r"online", m, re.I):
        return "Online (Zoom)" if re.search(r"zoom", m, re.I) else "Online"
    return re.sub(r"^(Offline\s+)?at\s+", "", m, flags=re.I)


def short_time(ev):
    t = ev["details"].get("Time", "")
    return re.sub(r"\s+to\s+", "–", t).replace(" IST", "")


def event_block(i, ev):
    meta = " · ".join(x for x in [short_date(ev), ev["details"].get("Duration", ""), short_mode(ev)] if x)
    lines = [f'*{i}. {ev["title"]}*', meta]
    if short_time(ev):
        lines.append(short_time(ev))
    if ev["link"]:
        lines.append(f'👉 {ev["link"]}')
    return "\n".join(lines)


def week_range(start):
    end = start + timedelta(days=6 - start.weekday())  # through Sunday
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%b}", end
    return f"{start:%d %b} – {end:%d %b}", end


def digest_events(events, start):
    _, end = week_range(start)
    this_week = sorted((e for e in events if e["start"] and start <= e["start"] <= end), key=lambda e: e["start"])
    later = sorted((e for e in events if e["start"] and e["start"] > end), key=lambda e: e["start"])
    return this_week, later[:1]


def format_digest(events, start):
    """Returns (caption, n_events_included, n_events_this_week) or None if nothing this week."""
    this_week, coming = digest_events(events, start)
    if not this_week:
        return None
    label, _ = week_range(start)
    head = [f"🗓️ *Events this week · {label}*", f"All events: {a.EVENTS_URL}"]
    tail = []
    if coming:
        c = coming[0]
        tail = ["", f'📌 *Coming up:* {c["title"]} · {short_date(c)}']

    # Drop events from the end until the caption fits, pointing to the site for the rest.
    for n in range(len(this_week), 0, -1):
        blocks = [event_block(i + 1, e) for i, e in enumerate(this_week[:n])]
        more = len(this_week) - n
        extra = [f"➕ {more} more this week on the events page"] if more else []
        text = "\n".join(head + [""] + "\n\n".join(blocks).split("\n") + ([""] + extra if extra else []) + tail)
        if len(text) <= CAPTION_LIMIT:
            return text, n, len(this_week)
    return text, 1, len(this_week)


# ---------- sending ----------

def send_image(chat_id, path, caption):
    if os.environ.get("DRY_RUN"):
        print(f"--- [DRY RUN] image {path.name} to {chat_id} ---\n{caption}\n")
        return
    base = (os.environ.get("GREEN_API_MEDIA_URL") or os.environ.get("GREEN_API_URL")
            or "https://api.green-api.com").rstrip("/")
    inst, token = os.environ["GREEN_API_INSTANCE"], os.environ["GREEN_API_TOKEN"]
    with path.open("rb") as f:
        r = requests.post(f"{base}/waInstance{inst}/sendFileByUpload/{token}", timeout=60,
                          data={"chatId": chat_id, "caption": caption},
                          files={"file": (path.name, f, "image/png")})
    r.raise_for_status()
    print(f"sent digest image to {chat_id}")


def check_connection():
    """Read-only check that the credentials work (sends nothing, uses no chat)."""
    base = (os.environ.get("GREEN_API_URL") or "https://api.green-api.com").rstrip("/")
    inst, token = os.environ.get("GREEN_API_INSTANCE", ""), os.environ.get("GREEN_API_TOKEN", "")
    if not (inst and token):
        print("Green-API check: GREEN_API_INSTANCE / GREEN_API_TOKEN not set")
        return
    try:
        r = requests.get(f"{base}/waInstance{inst}/getStateInstance/{token}", timeout=30)
        r.raise_for_status()
        print(f"Green-API check: instance state = {r.json().get('stateInstance')}")
    except requests.RequestException as e:
        print(f"Green-API check FAILED: {e.__class__.__name__} (status {getattr(e.response, 'status_code', '?')})")


def main():
    today = datetime.now(a.IST).date()
    if os.environ.get("DRY_RUN") and os.environ.get("DIGEST_DATE"):
        today = datetime.strptime(os.environ["DIGEST_DATE"], "%Y-%m-%d").date()  # preview a given week
        print(f"Previewing the digest for {today:%a %d %b %Y}")
    preview = "--preview" in sys.argv
    events = a.fetch_events()
    result = format_digest(events, today)
    banner = BANNER

    if preview:
        print(result[0] if result else "No events this week.")
        return

    groups = [g.strip() for g in os.environ.get("WA_GROUP_IDS", "").split(",") if g.strip()]
    if not groups:
        sys.exit("WA_GROUP_IDS is empty - run announce.py --list-groups to find group ids.")
    if os.environ.get("DRY_RUN"):
        check_connection()
    key = f"week of {today.isoformat()}"
    if ("digest", key) in a.load_log():
        print("Digest already sent this week.")
        return
    if result is None:
        print("No events this week - nothing sent.")
        return
    caption, n, total = result
    gap = int(os.environ.get("SEND_GAP_SECONDS", "90"))
    for i, g in enumerate(groups):
        if i and not os.environ.get("DRY_RUN"):
            time.sleep(gap)  # space out groups so it doesn't look like a burst
        try:
            send_image(g, banner, caption)
        except requests.RequestException as e:
            print(f"image send failed for {g} ({e}); falling back to text")
            a.send(g, "*ANTAR YOG FOUNDATION*\n\n" + caption)
    if not os.environ.get("DRY_RUN"):
        a.append_log("digest", key)
    print(f"Digest: {n} of {total} events this week, {len(caption)} chars")


if __name__ == "__main__":
    main()
