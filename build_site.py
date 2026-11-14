"""Build the status page (site/index.html) using the same logic digest.py sends with.

Usage: python build_site.py [--weeks 4]
"""

import html
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import announce as a
import digest as g

OUT = Path(__file__).with_name("site") / "index.html"
SLOT_TIME = "08:00 IST"


def wa_to_html(text):
    """Render WhatsApp formatting (*bold*, _italic_, links) as HTML."""
    out = []
    for line in text.split("\n"):
        s = html.escape(line)
        s = re.sub(r"(https?://[^\s<]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', s)
        s = re.sub(r"(?<![\w*])\*(?!\s)([^*]+?)\*(?!\w)", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w/])_(?!\s)([^_]+?)_(?![\w/])", r"<i>\1</i>", s)
        out.append(s)
    return "<br>".join(out)


DIGEST_DAY = 0  # Monday; must match the cron in announce.yml


def plan(events, rows, now, weeks):
    """Upcoming digest days. Returns list of (date, caption|None, n_included, n_total, banner_name)."""
    today = now.date()
    sent_weeks = {r["key"] for r in rows if r["kind"] == "digest"}
    d = today
    if d.weekday() != DIGEST_DAY or f"week of {d.isoformat()}" in sent_weeks or now.hour >= 12:
        d += timedelta(days=(DIGEST_DAY - d.weekday() - 1) % 7 + 1)
    slots = []
    while d <= today + timedelta(weeks=weeks):
        res = g.format_digest(events, d)
        name = f"banner-{d:%Y%m%d}.png"
        if res:
            g.make_banner(d, OUT.parent / name)
            slots.append((d, res[0], res[1], res[2], name))
        else:
            slots.append((d, None, 0, 0, name))
        d += timedelta(weeks=1)
    return slots


def bubble(caption, banner_name, tick=""):
    return (f'<div class="chat"><div class="bubble"><img src="{banner_name}" alt="Antar Yog Foundation · Events this week">'
            f'{wa_to_html(caption)}{f"<span class=tick>{tick}</span>" if tick else ""}</div></div>')


def build(weeks=4):
    now = datetime.now(a.IST)
    rows = a.read_log_rows()
    error = None
    try:
        events = a.fetch_events()
    except (Exception, SystemExit) as e:  # still publish a page that shows the problem
        events, error = [], str(e) or e.__class__.__name__

    OUT.parent.mkdir(exist_ok=True)
    for old in OUT.parent.glob("banner-*.png"):
        old.unlink()
    slots = plan(events, rows, now, weeks)
    first = slots[0][0] if slots else now.date()
    horizon = slots[-1][0] + timedelta(days=6) if slots else now.date()

    included = {}
    for d, cap, n, total, _ in slots:
        if cap:
            this_week, _ = g.digest_events(events, d)
            for i, ev in enumerate(this_week):
                included[ev["key"]] = (d, i < n)

    def status(ev):
        if ev["start"] is None:
            return "warn", "Date not understood"
        if ev["key"] in included:
            d, full = included[ev["key"]]
            return ("planned", f"In digest {d:%a %d %b}") if full else ("warn", f"Digest {d:%a %d %b} (as \"+ more\")")
        if ev["start"] < now.date():
            return "muted", "Already started"
        if ev["start"] < first:
            return "miss", "Starts before next digest — skipped"
        if ev["start"] > horizon:
            return "muted", "Later"
        return "miss", "Not included"

    days_label = a.WEEKDAYS[DIGEST_DAY].title()

    # ---- sections ----
    banner = f'<div class="banner bad">⚠️ Could not read the events page: {html.escape(error)}</div>' if error else ""

    nxt = next((s for s in slots if s[1]), None)
    if nxt:
        d, cap, n, total, name = nxt
        next_html = f"""
        <div class="next-meta">{d:%A %d %B} · {SLOT_TIME} · <span class="pill digest">Weekly digest · {total} event{"s" if total != 1 else ""}</span><span class="sub">{len(cap)}/1024 chars</span></div>
        {bubble(cap, name, SLOT_TIME[:5] + " ✓✓")}"""
    else:
        next_html = '<p class="empty">No events in the next few weeks.</p>'

    plan_rows = []
    for d, cap, n, total, name in slots:
        if cap:
            plan_rows.append(f"""
            <details class="row">
              <summary><span class="date">{d:%a %d %b}</span><span class="pill digest">{total} event{"s" if total != 1 else ""}</span><span class="title">{html.escape(", ".join(e["title"] for e in g.digest_events(events, d)[0]))}</span></summary>
              {bubble(cap, name)}
            </details>""")
        else:
            plan_rows.append(f'<div class="row idle"><span class="date">{d:%a %d %b}</span><span class="title">— no events, nothing sent —</span></div>')

    ev_rows = []
    for ev in sorted(events, key=lambda e: (e["start"] is None, e["start"] or now.date())):
        cls, label = status(ev)
        start = f'{ev["start"]:%d %b}' if ev["start"] else "?"
        link = f'<a href="{html.escape(ev["link"])}" target="_blank" rel="noopener">{html.escape(ev["title"])}</a>' if ev["link"] else html.escape(ev["title"])
        ev_rows.append(f'<tr><td>{link}<div class="sub">{html.escape(ev["date_text"])}</div></td><td class="nowrap">{start}</td><td><span class="status {cls}">{label}</span></td></tr>')

    hist_rows = [
        f'<tr><td class="nowrap">{html.escape(r["sent_at_ist"])}</td><td><span class="pill {r["kind"]}">{r["kind"].title()}</span></td><td>{html.escape(r["key"].split(" | ")[0])}</td></tr>'
        for r in reversed(rows)
    ]
    misses = sum(1 for ev in events if status(ev)[0] == "miss")
    planned = [s for s in slots if s[1]]

    page = TEMPLATE.format(
        updated=f"{now:%a %d %b %Y, %H:%M} IST",
        health='<span class="ok">● Events page OK</span>' if not error else '<span class="badtxt">● Events page error</span>',
        banner=banner,
        days=days_label,
        n_events=len(events),
        n_planned=len(planned),
        n_miss=misses,
        miss_cls="miss" if misses else "",
        next_html=next_html,
        weeks=weeks,
        plan_rows="".join(plan_rows),
        ev_rows="".join(ev_rows) or '<tr><td colspan="3" class="empty">No events found.</td></tr>',
        hist_rows="".join(hist_rows) or '<tr><td colspan="3" class="empty">Nothing sent yet.</td></tr>',
        source=a.EVENTS_URL,
    )
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT} ({len(events)} events, {len(planned)} digests planned, {misses} skipped)")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Event Announcer</title>
<style>
:root {{
  --bg: #f7f3ee; --card: #ffffff; --ink: #2b2420; --muted: #7a6f68; --line: #e8e0d8;
  --brand: #992E54; --brand-soft: #f6e6ec;
  --chat: #efe7dd; --bubble: #d9fdd3; --bubble-ink: #111b21;
  --ok: #2e7d4f; --ok-soft: #e3f3e9; --warn: #a15c00; --warn-soft: #fbefd9;
  --bad: #b3261e; --bad-soft: #fbe4e2; --blue: #2457a6; --blue-soft: #e4edfb;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #171412; --card: #221e1b; --ink: #f1ebe6; --muted: #a89d95; --line: #3a332e;
    --brand: #e07aa0; --brand-soft: #3a2230;
    --chat: #0b141a; --bubble: #005c4b; --bubble-ink: #e9edef;
    --ok: #6fcf97; --ok-soft: #1d3326; --warn: #f2b45c; --warn-soft: #3a2c16;
    --bad: #f28b82; --bad-soft: #3d1f1d; --blue: #8ab4f8; --blue-soft: #1c2a40;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color: var(--brand); }}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }}
header h1 {{ margin: 0; font-size: 1.5rem; letter-spacing: -.01em; }}
header h1 span {{ color: var(--brand); }}
.meta {{ color: var(--muted); font-size: .85rem; margin-top: 4px; display: flex; gap: 12px; flex-wrap: wrap; }}
.ok {{ color: var(--ok); }} .badtxt {{ color: var(--bad); }}
.banner {{ padding: 12px 14px; border-radius: 10px; margin-top: 16px; }}
.banner.bad {{ background: var(--bad-soft); color: var(--bad); }}
.stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 20px 0 8px; }}
.stat {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }}
.stat b {{ display: block; font-size: 1.5rem; line-height: 1.2; }}
.stat span {{ color: var(--muted); font-size: .8rem; }}
.stat.miss b {{ color: var(--bad); }}
section {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px; margin-top: 16px; }}
h2 {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 0 0 12px; }}
.next-meta {{ margin-bottom: 10px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.chat {{ background: var(--chat); border-radius: 12px; padding: 14px; }}
.bubble {{ background: var(--bubble); color: var(--bubble-ink); border-radius: 10px 10px 10px 2px; padding: 8px 10px 6px;
  max-width: 520px; font-size: 14.5px; line-height: 1.45; overflow-wrap: anywhere; box-shadow: 0 1px .5px rgba(0,0,0,.13); }}
.bubble a {{ color: #027eb5; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) .bubble a {{ color: #53bdeb; }} }}
.bubble img {{ display: block; width: 100%; border-radius: 6px; margin: -2px 0 8px; }}
.tick {{ display: block; text-align: right; font-size: 11px; opacity: .6; margin-top: 2px; }}
.pill {{ display: inline-block; font-size: .72rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }}
.pill.reminder {{ background: var(--warn-soft); color: var(--warn); }}
.pill.digest {{ background: var(--brand-soft); color: var(--brand); }}
.pill.announce {{ background: var(--blue-soft); color: var(--blue); }}
.row {{ border-top: 1px solid var(--line); }}
.row:first-of-type {{ border-top: 0; }}
.row summary, .row.idle {{ display: flex; align-items: center; gap: 10px; padding: 10px 2px; cursor: pointer; list-style: none; }}
.row summary::-webkit-details-marker {{ display: none; }}
.row summary::after {{ content: "▸"; margin-left: auto; color: var(--muted); transition: transform .15s; }}
.row[open] summary::after {{ transform: rotate(90deg); }}
.row[open] .chat {{ margin-bottom: 12px; }}
.row.idle {{ color: var(--muted); cursor: default; }}
.date {{ width: 84px; flex: none; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--muted); font-size: .9rem; }}
.title {{ min-width: 0; }}
.row summary .title {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ padding: 10px 6px; border-top: 1px solid var(--line); vertical-align: top; }}
tr:first-child td {{ border-top: 0; }}
.sub {{ color: var(--muted); font-size: .8rem; }}
.nowrap {{ white-space: nowrap; }}
.status {{ font-size: .78rem; font-weight: 600; padding: 2px 8px; border-radius: 6px; display: inline-block; }}
.status.sent {{ background: var(--ok-soft); color: var(--ok); }}
.status.planned {{ background: var(--blue-soft); color: var(--blue); }}
.status.miss {{ background: var(--bad-soft); color: var(--bad); }}
.status.warn {{ background: var(--warn-soft); color: var(--warn); }}
.status.muted {{ color: var(--muted); padding-left: 0; }}
.empty {{ color: var(--muted); }}
.note {{ color: var(--muted); font-size: .8rem; margin: 10px 0 0; }}
footer {{ color: var(--muted); font-size: .8rem; margin-top: 24px; text-align: center; }}
@media (max-width: 520px) {{
  .stat b {{ font-size: 1.2rem; }}
  .date {{ width: 72px; font-size: .82rem; }}
  section {{ padding: 14px; }}
}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Antar Yog <span>Event Announcer</span></h1>
    <div class="meta"><span>Updated {updated}</span>{health}<span>Weekly digest every {days}, 08:00 IST</span></div>
  </header>
  {banner}
  <div class="stats">
    <div class="stat"><b>{n_events}</b><span>upcoming events</span></div>
    <div class="stat"><b>{n_planned}</b><span>digests planned</span></div>
    <div class="stat {miss_cls}"><b>{n_miss}</b><span>events skipped</span></div>
  </div>

  <section>
    <h2>Next message</h2>
    {next_html}
  </section>

  <section>
    <h2>Planned schedule · next {weeks} weeks</h2>
    {plan_rows}
    <p class="note">Plan is based on the events page right now. New events added to the site will change it. Tap a row to see the message.</p>
  </section>

  <section>
    <h2>Events on the website</h2>
    <table>{ev_rows}</table>
  </section>

  <section>
    <h2>Sent history</h2>
    <table>{hist_rows}</table>
  </section>

  <footer>Source: <a href="{source}" target="_blank" rel="noopener">{source}</a></footer>
</div>
</body>
</html>
"""

if __name__ == "__main__":
    weeks = int(sys.argv[sys.argv.index("--weeks") + 1]) if "--weeks" in sys.argv else 4
    build(weeks)
