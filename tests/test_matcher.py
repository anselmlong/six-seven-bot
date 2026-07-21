import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sixseven.matcher import contains_six_seven, find_match


def test_digits_adjacent():
    assert contains_six_seven("67")
    assert contains_six_seven("6 7")
    assert contains_six_seven("6-7")
    assert contains_six_seven("the score was 6 7 baby")


def test_words():
    assert contains_six_seven("six seven")
    assert contains_six_seven("SIX SEVEN")
    assert contains_six_seven("he yelled six seven again")


def test_mixed_word_and_digit():
    assert contains_six_seven("six 7")
    assert contains_six_seven("6 seven")


def test_negatives():
    assert not contains_six_seven("")
    assert not contains_six_seven("just a normal caption")
    assert not contains_six_seven("7 6")  # wrong order
    assert not contains_six_seven("seven then a long gap then six")


def test_word_boundaries_not_confused():
    # "sixteen"/"seventeen"/"seventy" must not register as six/seven.
    assert not contains_six_seven("sixteen")
    assert not contains_six_seven("seventeen")
    assert not contains_six_seven("seventy sixers")


def test_snippet_returned():
    result = find_match("look: 6 7 !")
    assert result.matched
    assert "6" in result.snippet and "7" in result.snippet
