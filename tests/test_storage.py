import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.storage import Storage, week_bounds


def _insert_points(store, chat_id, user_id, name, uname, ts, n=1):
    """Backfill points_log rows with a controlled created_at (for window tests)."""
    with store._lock:
        for _ in range(n):
            store._conn.execute(
                "INSERT INTO points_log "
                "(chat_id, media_message_id, award_message_id, user_id, "
                " display_name, username, created_at) "
                "VALUES (?, 0, 0, ?, ?, ?, ?)",
                (chat_id, user_id, name, uname, ts),
            )
        store._conn.commit()


def test_increment_and_leaderboard(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    c1, _ = store.increment(1, 100, "Alice", "alice")
    c2, _ = store.increment(1, 100, "Alice", "alice")
    c3, _ = store.increment(1, 200, "Bob", "bob")
    assert (c1, c2, c3) == (1, 2, 1)

    assert store.user_count(1, 100) == 2
    assert store.user_count(1, 999) == 0

    board = store.leaderboard(1)
    assert board[0].user_id == 100
    assert board[0].count == 2
    assert board[1].user_id == 200

    store.close()


def test_counts_are_scoped_per_chat(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    store.increment(1, 100, "Alice", "alice")
    store.increment(2, 100, "Alice", "alice")

    assert store.user_count(1, 100) == 1
    assert store.user_count(2, 100) == 1
    assert len(store.leaderboard(1)) == 1

    store.close()


def test_is_first_time_dedup(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    # First call should return True
    assert store.is_first_time(1, 101) is True
    # Same message again should return False
    assert store.is_first_time(1, 101) is False
    assert store.is_first_time(1, 101) is False  # idempotent

    # Different message in same chat should be True
    assert store.is_first_time(1, 102) is True

    # Same message_id in different chat should be True
    assert store.is_first_time(2, 101) is True

    # Verify dedup survives a new Storage instance (simulates restart)
    store.close()
    store2 = Storage(db)
    assert store2.is_first_time(1, 101) is False  # still tracked
    assert store2.is_first_time(1, 999) is True   # new message

    store2.close()


def test_dispute_flow_and_half_majority(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    # 4 members have points; threshold is passed explicitly (fixed at 5 in the bot)
    store.increment(1, 100, "Alice", "alice")
    store.increment(1, 200, "Bob", "bob")
    store.increment(1, 300, "Cara", "cara")
    _, log_id = store.increment(1, 400, "Dan", "dan", media_message_id=555, award_message_id=777)
    store.update_award_message(log_id, 777)

    # award lookups
    assert store.points_log_by_award(1, 777)["user_id"] == 400
    assert store.points_log_by_award(1, 999) is None
    assert store.points_log_by_id(log_id)["media_message_id"] == 555

    # open a dispute on Dan's point
    d = store.open_dispute(1, log_id, 400, opened_by=100, threshold=3, expires_at=time.time() + 1000)
    assert d["status"] == "open"
    assert store.get_open_dispute(1, log_id)["id"] == d["id"]

    # voting: one vote per user, deduped, with names recorded
    assert store.dispute_vote(d["id"], 100, "Alice", "alice") == "voted"
    assert store.dispute_vote(d["id"], 100, "Alice", "alice") == "already_voted"
    assert store.dispute_vote(d["id"], 200, "Bob", "bob") == "voted"
    assert store.dispute_vote(d["id"], 300, "Cara", "cara") == "voted"
    assert store.dispute_vote_count(d["id"]) == 3
    assert [v["display_name"] for v in store.dispute_voters(d["id"])] == ["Alice", "Bob", "Cara"]

    # threshold reached -> overturn
    store.set_dispute_resolved(d["id"], "overturned")
    store.decrement(1, 400)
    assert store.user_count(1, 400) == 0  # was 1, overturned
    assert store.dispute_vote(d["id"], 200) == "resolved"  # resolved blocks votes


def test_global_leaderboard_sums_across_chats(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    # Alice: 2 in chat1 + 1 in chat2 = 3 total
    store.increment(1, 100, "Alice", "alice")
    store.increment(1, 100, "Alice", "alice")
    store.increment(2, 100, "Alice", "alice")
    # Bob: 5 in one chat
    for _ in range(5):
        store.increment(1, 200, "Bob", "bob")

    rows = store.global_leaderboard(limit=None)
    by_id = {r.user_id: r for r in rows}
    # Alice summed across both chats
    assert by_id[100].count == 3
    assert by_id[100].display_name == "Alice"
    # Bob 5 > Alice 3, so Bob ranks first
    assert rows[0].user_id == 200
    assert rows[0].count == 5


def test_global_leaderboard_name_from_highest_occurrence(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    # Same user in two chats under different names — the higher-count one wins.
    store.increment(1, 100, "Alice", "alice")
    store.increment(1, 100, "Alice", "alice")   # chat1 has 2
    store.increment(2, 100, "Al", "al")         # chat2 has 1
    row = store.global_leaderboard(limit=None)[0]
    assert row.count == 3
    assert row.display_name == "Alice"


def test_global_leaderboard_empty(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)
    assert store.global_leaderboard(limit=None) == []


def test_weekly_leaderboard_counts_only_current_week(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)
    now = time.time()
    day = 86400
    old = now - 8 * day  # within the previous, completed week
    # This week: Alice x2, Bob x1 (via increment, created_at=now).
    store.increment(1, 100, "Alice", "alice")
    store.increment(1, 100, "Alice", "alice")
    store.increment(1, 200, "Bob", "bob")
    # Last week: must be excluded from the weekly window.
    _insert_points(store, 1, 100, "Alice", "alice", old, n=3)
    _insert_points(store, 1, 200, "Bob", "bob", old, n=2)
    s, e = week_bounds()
    board = store.weekly_leaderboard(1, s, e, limit=None)
    by_id = {r.user_id: r for r in board}
    # Weekly board counts only in-window events, not the all-time totals.
    assert by_id[100].count == 2
    assert by_id[200].count == 1
    assert len(board) == 2
    # Total points_log rows = 8 (Alice 2 + Bob 1 current, +3 +2 backdated) —
    # the weekly window filters those down to the 2/1 shown above.
    with store._lock:
        n = store._conn.execute("SELECT COUNT(*) FROM points_log").fetchone()[0]
    assert n == 8
    store.close()


def test_weekly_leaderboard_name_from_latest_event(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)
    s, e = week_bounds()
    # Two in-window events; the later one's display name wins.
    _insert_points(store, 1, 100, "OldName", "old", s + (e - s) * 0.4)
    _insert_points(store, 1, 100, "NewName", "new", s + (e - s) * 0.6)
    row = store.weekly_leaderboard(1, s, e, limit=None)[0]
    assert row.display_name == "NewName"
    store.close()


def test_global_weekly_leaderboard_sums_across_chats(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)
    now = time.time()
    day = 86400
    old = now - 8 * day
    # This week: Alice 1 in chat1 + 2 in chat2. Bob 5 in chat1.
    store.increment(1, 100, "Alice", "alice")
    store.increment(2, 100, "Alice", "alice")
    store.increment(2, 100, "Alice", "alice")
    for _ in range(5):
        store.increment(1, 200, "Bob", "bob")
    # Old activity excluded.
    _insert_points(store, 1, 100, "Alice", "alice", old, n=10)
    s, e = week_bounds()
    rows = store.global_weekly_leaderboard(s, e, limit=None)
    by_id = {r.user_id: r for r in rows}
    assert by_id[100].count == 3  # 1 + 2, excludes the 10 backdated
    assert by_id[200].count == 5
    assert rows[0].user_id == 200  # Bob 5 > Alice 3
    store.close()


def test_chats_active_in_week_excludes_inactive(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)
    now = time.time()
    day = 86400
    store.increment(1, 100, "Alice", "alice")  # chat1 active this week
    _insert_points(store, 2, 100, "Alice", "alice", now - 8 * day)  # chat2 only old
    s, e = week_bounds()
    assert store.chats_active_in_week(s, e) == [1]
    store.close()


def _overturn(store, log_id):
    d = store.open_dispute(1, log_id, 100, 200, 3, time.time() + 300)
    store.set_dispute_resolved(d["id"], "overturned")


def test_overturned_points_drop_off_weekly_boards(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    store.increment(1, 100, "Alice", "alice")
    _, bad = store.increment(1, 100, "Alice", "alice")
    store.increment(1, 200, "Bob", "bob")
    assert not store.is_overturned(bad)
    _overturn(store, bad)
    assert store.is_overturned(bad)

    s, e = week_bounds()
    board = {r.display_name: r.count for r in store.weekly_leaderboard(1, s, e, limit=None)}
    assert board == {"Alice": 1, "Bob": 1}
    glob = {r.display_name: r.count for r in store.global_weekly_leaderboard(s, e, limit=None)}
    assert glob == {"Alice": 1, "Bob": 1}


def test_expired_dispute_keeps_the_point(tmp_path):
    store = Storage(str(tmp_path / "t.db"))
    _, log_id = store.increment(1, 100, "Alice", "alice")
    d = store.open_dispute(1, log_id, 100, 200, 3, time.time() + 300)
    store.set_dispute_resolved(d["id"], "expired")
    assert not store.is_overturned(log_id)
    s, e = week_bounds()
    assert store.weekly_leaderboard(1, s, e, limit=None)[0].count == 1
