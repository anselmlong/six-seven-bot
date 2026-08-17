import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.storage import Storage


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

    # voting: one vote per user, deduped
    assert store.dispute_vote(d["id"], 100) == "voted"
    assert store.dispute_vote(d["id"], 100) == "already_voted"
    assert store.dispute_vote(d["id"], 200) == "voted"
    assert store.dispute_vote(d["id"], 300) == "voted"
    assert store.dispute_vote_count(d["id"]) == 3

    # threshold reached -> overturn
    store.set_dispute_resolved(d["id"], "overturned")
    store.decrement(1, 400)
    assert store.user_count(1, 400) == 0  # was 1, overturned
    assert store.dispute_vote(d["id"], 200) == "resolved"  # resolved blocks votes
