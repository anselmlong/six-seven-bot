"""Pure text matching for the 'six seven' meme.

A hit is 6 and 7 appearing *together* — as digits ("67", "6 7", "6-7") or as
the words "six seven". This module has no external dependencies so it can be
unit-tested in isolation and reused by both the OCR and vision paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Whole words only, so "sixteen", "seventy", "sixty", "seventeen" don't count.
_SIX_WORD = re.compile(r"\bsix\b", re.IGNORECASE)
_SEVEN_WORD = re.compile(r"\bseven\b", re.IGNORECASE)

# 6 and 7 adjacent, allowing a small run of whitespace/punctuation between them
# ("67", "6 7", "6-7", "6/7"). After word->digit normalization this also catches
# "six seven" -> "6 7". Order-sensitive: the meme is "six seven", not "seven six".
_ADJACENT = re.compile(r"6[\s\W]{0,3}7")

# Same but for 69 ("69", "6 9", "6-9", "6/9", "six nine" -> "6 9" -> "69").
_ADJACENT_69 = re.compile(r"6[\s\W]{0,3}9")

_NINE_WORD = re.compile(r"\bnine\b", re.IGNORECASE)


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    snippet: str = ""
    kind: str = ""  # "67" or "69"


def _normalize(text: str) -> str:
    """Lowercase and turn the standalone words six/seven/nine into digits."""
    text = _SIX_WORD.sub("6", text)
    text = _SEVEN_WORD.sub("7", text)
    text = _NINE_WORD.sub("9", text)
    return text.lower()


def find_match(text: str) -> MatchResult:
    """Return whether `text` contains a 'six seven' or '69', plus which kind."""
    if not text:
        return MatchResult(False)
    normalized = _normalize(text)
    # Check 69 first so "6 9" doesn't also match the 67 pattern
    m = _ADJACENT_69.search(normalized)
    if m:
        return MatchResult(True, snippet=m.group(0).strip(), kind="69")
    m = _ADJACENT.search(normalized)
    if m:
        return MatchResult(True, snippet=m.group(0).strip(), kind="67")
    return MatchResult(False)


def contains_six_seven(text: str) -> bool:
    return find_match(text).matched


def find_matches(text: str) -> list[MatchResult]:
    """Return all matches found in text (e.g. both '69' and '67')."""
    if not text:
        return []
    normalized = _normalize(text)
    results = []
    if _ADJACENT_69.search(normalized):
        results.append(MatchResult(True, kind="69"))
    if _ADJACENT.search(normalized):
        results.append(MatchResult(True, kind="67"))
    return results
