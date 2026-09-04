import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.bot import _format_celebration_message, _format_reset_message
from sixseven.storage import LeaderRow


def test_reset_message_shows_final_standings():
    rows = [
        LeaderRow(1, "Alice", "alice", 12),
        LeaderRow(2, "Bob", "bob", 7),
        LeaderRow(3, "Cara", "cara", 3),
    ]
    msg = _format_reset_message(rows)
    assert "final leaderboard" in msg
    assert "🥇 Alice — 12 67s" in msg
    assert "🥈 Bob — 7 67s" in msg
    assert "🥉 Cara — 3 67s" in msg
    assert "everyone starts fresh" in msg


def test_reset_message_empty_leaderboard():
    assert _format_reset_message([]) == "leaderboard reset — everyone starts fresh 🫡"


def test_reset_message_html_escapes_names():
    rows = [LeaderRow(1, "A<B&C", "", 5)]
    msg = _format_reset_message(rows)
    assert "<B" not in msg
    assert "A&lt;B&amp;C" in msg


def test_celebration_message_crowns_top_week_and_global_champ():
    rows = [
        LeaderRow(1, "Alice", "alice", 12),
        LeaderRow(2, "Bob", "bob", 7),
        LeaderRow(3, "Cara", "cara", 3),
    ]
    g_champ = LeaderRow(9, "@globalguy", "globalguy", 42)
    msg = _format_celebration_message(rows, g_champ)
    assert "SIX SEVENER OF THE WEEK" in msg
    assert "the top 67er of the week is Alice with 12 67s 👑! well played!!" in msg
    assert "🥇 Alice — 12 67s" in msg
    assert "🥉 Cara — 3 67s" in msg
    assert "@globalguy" in msg and "with 42 67s this week" in msg
    assert "go defend the crown" in msg


def test_celebration_message_without_global_champ():
    rows = [LeaderRow(1, "Alice", "alice", 3)]
    msg = _format_celebration_message(rows)
    assert "global champ" not in msg
    assert "the top 67er of the week is Alice with 3 67s 👑! well played!!" in msg


def test_celebration_message_html_escapes_names():
    rows = [LeaderRow(1, "A<B", "", 2)]
    msg = _format_celebration_message(rows)
    assert "A&lt;B" in msg and "<B" not in msg
