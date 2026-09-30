"""Animated bar-chart race of cumulative 67s per person in a chat.

Rendered from points_log (one row per awarded point) with matplotlib's
FuncAnimation → GIF via Pillow. One frame per distinct event timestamp, so
gif length scales naturally with chat activity (uncapped).
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import matplotlib

matplotlib.use("Agg")  # headless container — never touch a display
import matplotlib.animation as animation
import matplotlib.pyplot as plt

from .storage import NOT_OVERTURNED_SQL

log = logging.getLogger(__name__)

_SGT = timezone(timedelta(hours=8))
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\uFE0F]"
)

# DejaVu Sans ships with matplotlib and covers Latin + common scripts; any
# glyph outside it (emoji etc.) would render as a box, so strip those.
def _clean_name(name: str) -> str:
    return _EMOJI_RE.sub("", name).strip() or "anon"


def render_race(db_path: str, chat_id: int, since_days: int | None = None, fps: int = 8, out_dir: str = "/tmp") -> str | None:
    """Render the race gif for one chat. Returns the file path, or None if
    the chat has fewer than 2 hits (nothing to animate).

    since_days: restrict to hits from the last N days (None = all time).
    """
    import sqlite3

    since_ts: int | None = None
    if since_days is not None:
        cutoff = datetime.now(_SGT) - timedelta(days=since_days)
        since_ts = int(cutoff.timestamp())

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if since_ts is None:
            rows = conn.execute(
                f"""
                SELECT user_id,
                       MAX(COALESCE(NULLIF(display_name,''), NULLIF(username,''), 'anon')),
                       created_at
                FROM points_log
                WHERE chat_id = ? AND {NOT_OVERTURNED_SQL}
                GROUP BY user_id, created_at
                ORDER BY created_at
                """,
                (chat_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT user_id,
                       MAX(COALESCE(NULLIF(display_name,''), NULLIF(username,''), 'anon')),
                       created_at
                FROM points_log
                WHERE chat_id = ? AND created_at >= ? AND {NOT_OVERTURNED_SQL}
                GROUP BY user_id, created_at
                ORDER BY created_at
                """,
                (chat_id, since_ts),
            ).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return None

    series: dict[int, list[int]] = defaultdict(list)
    names: dict[int, str] = {}
    for uid, name, ts in rows:
        series[uid].append(ts)
        names[uid] = _clean_name(name or "anon")

    # dedupe identical timestamps (two hits same second → still two events,
    # but frames are per unique ts to avoid zero-width steps)
    all_ts = sorted({ts for hits in series.values() for ts in hits})
    top_uids = sorted(series, key=lambda u: -len(series[u]))[:10]

    fig, ax = plt.subplots(figsize=(7.5, 5.2), dpi=80)
    colors = plt.cm.tab10(range(len(top_uids)))
    color_of = {uid: colors[i % 10] for i, uid in enumerate(top_uids)}

    def counts_at(tcut: int) -> list[tuple[str, int, int]]:
        items = []
        for uid in top_uids:
            n = sum(1 for ts in series[uid] if ts <= tcut)
            if n > 0:
                items.append((names[uid], n, uid))
        items.sort(key=lambda x: x[1])
        return items

    def update(i: int):
        ax.clear()
        t = datetime.fromtimestamp(all_ts[i], _SGT)
        items = counts_at(all_ts[i])
        labels = [x[0] for x in items]
        vals = [x[1] for x in items]
        cols = [color_of.get(x[2], "#888") for x in items]
        bars = ax.barh(labels, vals, color=cols)
        vmax = max(vals) if vals else 1
        ax.set_xlim(0, vmax * 1.18)
        for b, v in zip(bars, vals):
            ax.text(v + vmax * 0.02, b.get_y() + b.get_height() / 2,
                    str(v), va="center", fontsize=10)
        ax.set_title(f"67 race · {t.strftime('%d %b %H:%M')}", fontsize=13)
        ax.tick_params(axis="y", labelsize=10)

    # NOTE: PillowWriter + ani.save() can silently emit only the first frame
    # if the animator is GC'd mid-save (the "chart stops at the beginning"
    # bug). Drive the writer frame-by-frame instead — explicit, no GC race.
    os.makedirs(out_dir, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".gif", dir=out_dir)
    os.close(fd)
    start = time.time()
    writer = animation.PillowWriter(fps=fps)
    writer.setup(fig=fig, outfile=path, dpi=fig.dpi)
    for i in range(len(all_ts)):
        update(i)
        writer.grab_frame(facecolor="white")
    writer.finish()
    plt.close(fig)
    log.info("flow: rendered %d-frame race for chat %s in %.1fs", len(all_ts), chat_id, time.time() - start)
    return path
