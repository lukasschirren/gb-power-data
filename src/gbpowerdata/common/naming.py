"""Shared plant/site name normalisation + keyword extraction.

Stage 1 (CfD <-> plant matching) and the REPD helper both reduce free-text
plant names to a canonical form and pick a distinctive keyword for substring
matching. The logic lives here so the two stay in sync.
"""

from __future__ import annotations

import re

# Generic words that never distinguish one site from another.
KEYWORD_STOP = {"PROJECT", "OFFSHORE", "ONSHORE", "FLOATING", "EXTENSION",
                "PHASE", "POWER", "WINDFARM", "ENERGY", "SOLAR", "SCHEME",
                "FARM", "WIND", "PARK", "STATION", "PLANT", "LIMITED"}


def normalise(s: str) -> str:
    """Upper-case and collapse punctuation to single spaces. Non-strings -> ""."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^A-Z0-9 ]+", " ", s.upper()).strip()


def keyword(name: str, *, stop: set[str] | None = None, min_len: int = 5,
            fallback: str | None = "normalise") -> str | None:
    """Pick the longest distinctive word from `name` (e.g. HORNSEA).

    `stop` overrides the default stop-word set. `fallback` controls the result
    when no word qualifies: "normalise" returns normalise(name); None returns None.
    """
    stop = KEYWORD_STOP if stop is None else stop
    words = [w for w in normalise(name).split() if len(w) >= min_len and w not in stop]
    if words:
        return max(words, key=len)
    return normalise(name) if fallback == "normalise" else None
