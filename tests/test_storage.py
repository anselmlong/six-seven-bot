import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.storage import Storage


def test_increment_and_leaderboard(tmp_path):
    db = str(tmp_path / "t.db")
    store = Storage(db)

    assert store.increment(1, 100, "Alice", "alice") == 1
    assert store.increment(1, 100, "Alice", "alice") == 2
    assert store.increment(1, 200, "Bob", "bob") == 1

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
