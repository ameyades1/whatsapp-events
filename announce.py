"""Shared helpers for digest.py: scrape Antar Yog events, send via Green-API, sent-log.csv.

Env vars:
  GREEN_API_INSTANCE, GREEN_API_TOKEN   credentials from console.green-api.com
  GREEN_API_URL                         optional, default https://api.green-api.com
  DRY_RUN=1                             print messages instead of sending

Usage:
  python announce.py --list-groups  print your groups and their ids
"""

import csv
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

EVENTS_URL = "https://antaryogfoundation.in/events"
LOG_FILE = Path(__file__).with_name("sent-log.csv")
IST = timezone(timedelta(hours=5, minutes=30))
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ---------- scraping ----------

def parse_start_date(text):
    """'Sat, 28 Nov to Sun, 29 Nov 2026' -> date(2026, 11, 28)."""
    days = [(int(d), MONTHS[mo[:3].lower()])
            for d, mo in re.findall(r"(\d{1,2})\s+([A-Za-z]{3,})", text) if mo[:3].lower() in MONTHS]
    years = re.findall(r"\b(20\d\d)\b", text)
    if not (days and years):
        return None
    year = int(years[0])
    # 'Sat, 28 Dec to Sun, 3 Jan 2027': the only year belongs to the end date.
    if len(years) == 1 and len(days) > 1 and days[0][1] > days[-1][1]:
        year -= 1
    return date(year, days[0][1], days[0][0])


def clean(s):
    return re.sub(r"\s+", " ", s).strip()


def scrape_events(html):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find(id="upcomingEvents")
    if section is None:
        raise RuntimeError("Could not find #upcomingEvents - has the page layout changed?")
    events = []
    for card in section.select("div.event"):
        name = card.select_one(".event-name")
        when = card.select_one(".event-date")
        if not (name and when):
            continue
        ev = {"title": clean(name.get_text()), "date_text": clean(when.get_text()),
              "details": {}, "headline": "", "body": "", "link": ""}
        ev["start"] = parse_start_date(ev["date_text"])
        for p in card.select(".event-detail p"):
            label = p.find("strong")
            if not label:
                continue
            key = clean(label.get_text()).rstrip(":")
            if key == "Benefit for you":
                strongs = p.find_all("strong")
                ev["headline"] = clean(strongs[1].get_text()) if len(strongs) > 1 else ""
                for s in strongs:
                    s.extract()
                ev["body"] = clean(p.get_text())
            else:
                label.extract()
                ev["details"][key] = clean(p.get_text())
        a = card.select_one("a.register-button") or card.select_one("a[href]")
        if a:
            ev["link"] = a["href"].strip()
        ev["key"] = f'{ev["title"]} | {ev["date_text"]}'
        events.append(ev)
    return events


# ---------- message ----------

# ---------- Green-API ----------

def api(method, path, **kw):
    base = (os.environ.get("GREEN_API_URL") or "https://api.green-api.com").rstrip("/")
    inst, token = os.environ["GREEN_API_INSTANCE"], os.environ["GREEN_API_TOKEN"]
    r = requests.request(method, f"{base}/waInstance{inst}/{path}/{token}", timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def send(chat_id, text):
    if os.environ.get("DRY_RUN"):
        print(f"--- [DRY RUN] to {chat_id} ---\n{text}\n")
        return
    api("POST", "sendMessage", json={"chatId": chat_id, "message": text})
    print(f"sent to {chat_id}: {text.splitlines()[0]}")


def list_groups():
    for c in api("GET", "getContacts"):
        if c.get("type") == "group" or c.get("id", "").endswith("@g.us"):
            print(f'{c["id"]}\t{c.get("name", "")}')


# ---------- log ----------

def read_log_rows():
    if not LOG_FILE.exists():
        return []
    with LOG_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))



def append_log(kind, key):
    new = not LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["sent_at_ist", "kind", "key"])
        w.writerow([datetime.now(IST).strftime("%Y-%m-%d %H:%M"), kind, key])


# ---------- schedule ----------

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]




# ---------- main ----------

def main():
    if "--list-groups" in sys.argv:
        list_groups()
    else:
        print(__doc__)


def fetch_events():
    resp = requests.get(EVENTS_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    events = scrape_events(resp.text)
    if not events:
        sys.exit("No events found on the page - has the layout changed?")
    return events


if __name__ == "__main__":
    main()
