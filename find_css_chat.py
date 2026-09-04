"""Resolve the 'CSS 6767' group's chat_id by matching getChat titles.

Loads the bot token from .env (never prints it), queries getChat for each
known chat_id, and reports any whose title matches the CSS 6767 group.
"""
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

# Load .env minimally without echoing the token.
env_path = "/home/ubuntu/six-seven-bot/.env"
token = ""
with open(env_path) as fh:
    for line in fh:
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
if not token:
    sys.exit("TELEGRAM_BOT_TOKEN not found in .env")

db_path = "/home/ubuntu/six-seven-bot/data/sixseven.db"
db = sqlite3.connect(db_path)
chat_ids = [r[0] for r in db.execute("SELECT DISTINCT chat_id FROM points_log")]
db.close()

target = "css 6767"


def get_chat(cid):
    url = f"https://api.telegram.org/bot{token}/getChat?chat_id={cid}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read().decode(), None
    except Exception as exc:
        return None, str(exc)


for cid in chat_ids:
    body, err = get_chat(cid)
    if body is None:
        print(f"{cid}: ERROR {err}")
        continue
    import json

    data = json.loads(body)
    if data.get("ok"):
        ch = data["result"]
        title = ch.get("title") or ""
        print(f"{cid}: title={title!r}")
        if target in title.lower():
            print(f"  ^^ MATCH — id={cid}")
    else:
        print(f"{cid}: api_error={data.get('description')}")