"""Twice-weekly WhatsApp posts: the fixed logo banner (assets/banner.png) + a caption.

  Sunday 09:43 IST    "weekly"   full list of events starting Mon–Sun of the coming week.
  Thursday 19:17 IST  "teaching" one message from wa-messages/ (see teaching.py),
                                 sent as text so the YouTube preview shows.

Each post is recorded in sent-log.csv (kind weekly/teaching), plus one "included"
row per event it listed.

Env vars: same as announce.py (GREEN_API_*, WA_GROUP_IDS, DRY_RUN), plus
  GREEN_API_MEDIA_URL   host for file uploads (shown in the Green-API console)
  SEND_GAP_SECONDS      pause between groups (default 90)
  DIGEST_DATE           dry/test run only: pretend today is this date (YYYY-MM-DD)
  TEST_SEND=1           really send, but don't record it in the log
  DIGEST_KIND           force "weekly" or "teaching" regardless of the day

Usage:
  python digest.py                 send today's post (if today is a send day)
  python digest.py --preview       print today's caption without sending
"""

import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

import announce as a
import teaching as t

ROOT = Path(__file__).parent
BANNER = ROOT / "assets" / "banner.png"   # fixed image, made once from the site's logo
CAPTION_LIMIT = 1000          # WhatsApp caption limit is ~1024; keep a margin

# weekday -> post kind; keep in sync with the crons in .github/workflows/announce.yml
SEND_DAYS = {6: "weekly", 3: "teaching"}
SEND_TIME = {"weekly": "09:43", "teaching": "19:17"}
LABEL = {"weekly": "Events this week", "teaching": "Teaching"}


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


def nice_time(ev):
    """'Morning 7 AM to 10 AM | Evening 6:45 PM to 9:45 PM IST' -> '7–10 AM or 6:45–9:45 PM'."""
    t = ev["details"].get("Time", "")
    t = re.sub(r"\b(Morning|Evening|Afternoon|Night)\s+", "", t, flags=re.I).replace(" IST", "")
    t = re.sub(r"(\d)\.(\d\d)", r"\1:\2", t)
    parts = []
    for part in t.split("|"):
        part = part.strip()
        m = re.match(r"^(\S+)\s*(AM|PM)\s+to\s+(\S+)\s*(AM|PM)(.*)$", part, re.I)
        if m:
            a1, p1, b, p2, rest = m.groups()
            part = (f"{a1}–{b} {p2}" if p1.upper() == p2.upper() else f"{a1} {p1}–{b} {p2}") + rest
        parts.append(part)
    return " or ".join(p for p in parts if p)


def full_block(ev, i=None):
    """Sunday format: title, how/where + when, time."""
    d = ev["details"]
    mode = d.get("Mode") or d.get("Venue") or ""
    when = re.sub(r"\s*onwards", "", short_date(ev))
    if "onwards" in ev["date_text"].lower():
        when = f"from {when}"
    dur = d.get("Duration", "").strip().lower()
    if dur and dur != "1 day" and " – " not in when:
        when = (when if when.startswith("from ") else f"from {when}") + f", {dur}"
    if re.search(r"online", mode, re.I):
        line = f"💻 Online · {when}"
    elif mode:
        line = f"📍 {re.sub(r'^(Offline\s+)?at\s+', '', mode, flags=re.I)} · {when}"
    else:
        line = f"📅 {when}"
    lines = [f'*{i}. {ev["title"]}*' if i else f'*{ev["title"]}*', line]
    if nice_time(ev):
        lines.append(f"🕖 {nice_time(ev)}")
    return "\n".join(lines)


def date_range(s, e, weekday=False):
    fmt = (lambda d, m: f"{d:%a} {d.day}" + (f" {d:%b}" if m else "")) if weekday else \
          (lambda d, m: f"{d.day}" + (f" {d:%b}" if m else ""))
    if s.month == e.month:
        return f"{fmt(s, False)}–{fmt(e, True)}" if not weekday else f"{fmt(s, False)} – {fmt(e, True)}"
    return f"{fmt(s, True)} – {fmt(e, True)}"


def window(kind, d):
    """Date range of events a post on day d covers."""
    return d + timedelta(1), d + timedelta(7)          # Sun -> Mon..Sun


def by_start(evs):
    return sorted(evs, key=lambda e: e["start"])


def compose(kind, events, d, mentioned=None):
    """Build the caption for a post of `kind` sent on date d.

    Returns dict(caption, included=[events in the caption], total) or None if nothing to send.
    For "teaching", `mentioned` holds keys already sent, so the next unsent message is chosen.
    """
    if kind == "teaching":
        item = t.pick(mentioned or set(), d)
        if not item:
            return None
        post = {"caption": t.format_post(item), "included": [item], "total": 1}
        if item.get("image"):
            post["image"] = item["image"]   # course post: its own picture + caption
        else:
            post["text_only"] = True        # YouTube teaching: text, so the preview shows
        return post
    s, e = window(kind, d)
    main = by_start(x for x in events if x["start"] and s <= x["start"] <= e)
    if not main:
        return None

    head = [f"🗓️ *Events this week · {date_range(s, e)}*"]

    def render(n):
        blocks = [full_block(x, i + 1) for i, x in enumerate(main[:n])]
        parts = head + [""] + "\n\n".join(blocks).split("\n")
        if n < len(main):
            parts += ["", f"➕ {len(main) - n} more on the events page"]
        parts += ["", "*Details & registration:*", a.EVENTS_URL, "", "Everyone is welcome 🙏"]
        return "\n".join(parts)

    # Drop events from the end until the caption fits.
    n = len(main)
    text = render(n)
    while len(text) > CAPTION_LIMIT and n > 1:
        n -= 1
        text = render(n)
    return {"caption": text, "included": main[:n], "total": len(main)}


def kind_for(d):
    return os.environ.get("DIGEST_KIND") or SEND_DAYS.get(d.weekday())


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
                          files={"file": (path.name, f, mimetypes.guess_type(path.name)[0] or "image/jpeg")})
    r.raise_for_status()
    print(f"sent image post to {chat_id}")


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


def mentioned_keys(rows):
    return {r["key"] for r in rows if r["kind"] == "included"}


def main():
    dry = bool(os.environ.get("DRY_RUN"))
    test = bool(os.environ.get("TEST_SEND"))   # real send, but not logged
    today = datetime.now(a.IST).date()
    if (dry or test) and os.environ.get("DIGEST_DATE"):
        today = datetime.strptime(os.environ["DIGEST_DATE"], "%Y-%m-%d").date()
        print(f"Previewing as if today were {today:%a %d %b %Y}")
    kind = kind_for(today)
    if not kind:
        print(f"{today:%A} is not a send day ({', '.join(f'{a.WEEKDAYS[k].title()}={v}' for k, v in SEND_DAYS.items())}).")
        return

    events = a.fetch_events()
    rows = a.read_log_rows()
    post = compose(kind, events, today, mentioned_keys(rows))

    if "--preview" in sys.argv:
        print(post["caption"] if post else f"Nothing to send for the {kind} post.")
        return

    groups = [g.strip() for g in os.environ.get("WA_GROUP_IDS", "").split(",") if g.strip()]
    if not groups:
        sys.exit("WA_GROUP_IDS is empty - run announce.py --list-groups to find group ids.")
    if dry:
        check_connection()
    key = f"{kind} {today.isoformat()}"
    if not test and any(r["kind"] == kind and r["key"] == key for r in rows):
        print(f"The {kind} post for {today} was already sent.")
        return
    if post is None:
        print(f"Nothing to send for the {kind} post - skipped.")
        return

    gap = int(os.environ.get("SEND_GAP_SECONDS", "90"))
    for i, g in enumerate(groups):
        if i and not dry:
            time.sleep(gap)  # space out groups so it doesn't look like a burst
        if post.get("text_only"):
            a.send(g, post["caption"])   # text, so WhatsApp shows the YouTube preview
            continue
        try:
            send_image(g, post.get("image") or BANNER, post["caption"])
        except requests.RequestException as e:
            print(f"image send failed for {g} ({e}); falling back to text")
            a.send(g, post["caption"] if post.get("image") else "*ANTAR YOG FOUNDATION*\n\n" + post["caption"])
    if test:
        print("TEST SEND - not recorded in sent-log.csv")
    elif not dry:
        a.append_log(kind, key)
        for ev in post["included"]:
            a.append_log("included", ev["key"])
    print(f"{kind}: {post['total']} events, {len(post['caption'])} chars")


if __name__ == "__main__":
    main()
