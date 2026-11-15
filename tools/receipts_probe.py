"""Read-only Green-API probe: can we count who read our group posts?

Sends nothing to WhatsApp. It reads:
  1. account settings: are outgoing-message status notifications on?
  2. our recent posts in each group (getChatHistory) and their status;
  3. the status of the newest post (getMessage);
  4. pending notifications (receiveNotification), summarised by type/status.
Notifications are left in the queue unless DRAIN=1, which deletes the ones it
reads (that only affects Green-API's queue, not WhatsApp).

The repo is public, so its Actions logs are too: group ids and phone numbers are
masked and message text is cut to the first line.
"""

import json
import os
import re
import time
from collections import Counter

import requests

BASE = (os.environ.get("GREEN_API_URL") or "https://api.green-api.com").rstrip("/")
INST, TOKEN = os.environ["GREEN_API_INSTANCE"], os.environ["GREEN_API_TOKEN"]
GROUPS = [g.strip() for g in os.environ.get("WA_GROUP_IDS", "").split(",") if g.strip()]


def mask(s):
    """Hide all but the last 4 digits of any phone number / group id in s."""
    return re.sub(r"\d{5,}", lambda m: "…" + m.group()[-4:], str(s))


def call(method, path, suffix="", **kw):
    r = requests.request(method, f"{BASE}/waInstance{INST}/{path}/{TOKEN}{suffix}", timeout=40, **kw)
    r.raise_for_status()
    return r.json() if r.text.strip() else None


def first_line(m):
    text = m.get("textMessage") or m.get("caption") or m.get("typeMessage") or ""
    return text.strip().splitlines()[0][:60] if text.strip() else ""


print("== 1. Settings (notification switches only)")
settings = call("GET", "getSettings")
for k, v in sorted(settings.items()):
    if "webhook" in k.lower() and k != "webhookUrl" and "token" not in k.lower():
        print(f"  {k}: {v}")
print(f"  webhookUrl set: {'yes' if settings.get('webhookUrl') else 'no'}")
print(f"  instance state: {call('GET', 'getStateInstance').get('stateInstance')}")

print("\n== 2. Our recent posts per group")
newest = None
for i, g in enumerate(GROUPS):
    if i:
        time.sleep(15)  # getChatHistory is rate-limited (got HTTP 429 back-to-back)
    hist = call("POST", "getChatHistory", json={"chatId": g, "count": 30}) or []
    ours = [m for m in hist if m.get("type") == "outgoing"]
    print(f"  group {mask(g)}: {len(hist)} recent messages, {len(ours)} sent by us")
    for m in ours[:3]:
        extra = {k: v for k, v in m.items() if re.search(r"status|read|deliver", k, re.I)}
        print(f"    {m.get('timestamp')}  {m.get('typeMessage')}  status={m.get('statusMessage')}  "
              f"{json.dumps(extra)}  | {first_line(m)}")
        if newest is None or m.get("timestamp", 0) > newest[1].get("timestamp", 0):
            newest = (g, m)
    if ours:
        print(f"    fields on a message: {sorted(ours[0])}")

print("\n== 3. getMessage on our newest post")
if newest:
    g, m = newest
    full = call("POST", "getMessage", json={"chatId": g, "idMessage": m["idMessage"]})
    print(f"  group {mask(g)}, sent {m.get('timestamp')}")
    print(f"  fields: {sorted(full)}")
    print(f"  status-like fields: {mask(json.dumps({k: v for k, v in full.items() if re.search(r'status|read|deliver|receipt', k, re.I)}))}")
else:
    print("  no posts of ours found")

print("\n== 4. Pending notifications (up to 50)")
drain = os.environ.get("DRAIN") == "1"
kinds, statuses, seen = Counter(), Counter(), 0
for _ in range(50):
    n = call("GET", "receiveNotification", suffix="?receiveTimeout=5")
    if not n:
        break
    seen += 1
    body = n.get("body", {})
    kinds[body.get("typeWebhook")] += 1
    if body.get("typeWebhook") == "outgoingMessageStatus":
        statuses[(body.get("status"), "group" if str(body.get("chatId", "")).endswith("@g.us") else "1:1",
                  "has sender" if any(k in body for k in ("senderData", "participant", "sender")) else "no sender")] += 1
        if statuses.total() == 1:
            print(f"  sample status notification keys: {sorted(body)}")
            print(f"  sample (masked): {mask(json.dumps(body))[:600]}")
    if drain:
        call("DELETE", "deleteNotification", suffix=f"/{n['receiptId']}")
    else:
        break  # without deleting, the queue keeps returning the same first item
print(f"  read {seen} notification(s){' and deleted them' if drain else ' (left in queue; run with drain to see more)'}")
print(f"  by type: {dict(kinds)}")
print(f"  outgoing statuses (status, chat, sender info): {dict(statuses)}")
