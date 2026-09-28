"""Send a real weekly-celebration test message to the CSS 6767 group (-1004357298330).

Reads the DB read-only (the db file is root-owned by the docker container, so
Storage()'s write-cleanup would fail). Builds the celebration text from the
chat's actual current-week standings + the global champ, sends via sendMessage.
"""
import json
import sqlite3
import sys
import urllib.parse
import urllib.request

env_path = "/home/ubuntu/six-seven-bot/.env"
token = ""
with open(env_path) as fh:
    for line in fh:
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
if not token:
    sys.exit("TELEGRAM_BOT_TOKEN not found in .env")

CHAT = -1004357298330
sys.path.insert(0, "/home/ubuntu/six-seven-bot/src")
from sixseven.storage import LeaderRow, week_bounds
from sixseven.bot import _format_celebration_message

db = sqlite3.connect(
    "file:/home/ubuntu/six-seven-bot/data/sixseven.db?mode=ro",
    uri=True,
)
db.row_factory = sqlite3.Row


def weekly_rows(chat_scoped, start, end, limit):
    cond = "r.chat_id = ? AND " if chat_scoped else ""
    # chat-scoped WHERE clauses each need the chat_id too:
    # {cond}...>=? AND ...<?  ->  [CHAT, s, e] per CTE, x2 CTEs
    core = [CHAT, start, end] if chat_scoped else [start, end]
    params = list(core) * 2  # once for ranked, once for agg
    sql = f"""
        WITH ranked AS (
            SELECT user_id, display_name, username, created_at,
                   ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) rn
            FROM points_log r WHERE {cond}created_at >= ? AND created_at < ?
        ),
        agg AS (
            SELECT user_id, COUNT(*) cnt, MAX(created_at) last_hit
            FROM points_log r WHERE {cond}created_at >= ? AND created_at < ?
            GROUP BY user_id
        )
        SELECT r.user_id, r.display_name, r.username, a.cnt count, a.last_hit
        FROM ranked r JOIN agg a ON a.user_id=r.user_id WHERE r.rn=1
        ORDER BY a.cnt DESC, a.last_hit ASC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = db.execute(sql, params).fetchall()
    return [
        LeaderRow(r["user_id"], r["display_name"], r["username"], int(r["count"]))
        for r in rows
    ]


s, e = week_bounds()
rows = weekly_rows(True, s, e, None)
g = weekly_rows(False, s, e, 1)
g_champ = g[0] if g else None

text = _format_celebration_message(rows, g_champ)
print("=== MESSAGE PREVIEW ===\n")
print(text)
print("\n=== SENDING ===")

body = urllib.parse.urlencode(
    {"chat_id": CHAT, "text": text, "parse_mode": "HTML"}
).encode()
req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode())
    if resp.get("ok"):
        print("SENT ✓  message_id:", resp["result"]["message_id"])
    else:
        print("API ERROR:", resp.get("description"))
except Exception as exc:
    print("SEND FAILED:", exc)