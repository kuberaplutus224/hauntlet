"""The fixed copy matches the requirements' table (scorecard task 7.4).

**Validates: scorecard Requirements 1.1, 1.2**
"""

from __future__ import annotations

import re
from pathlib import Path

from hauntlet.scorecard import copy

REQUIREMENTS = Path(__file__).resolve().parents[1] / ".kiro" / "specs" / "scorecard" / "requirements.md"
ROW = re.compile(r"^\| (C\d+) \| [^|]+ \| (.+) \|$")


def _table() -> dict[str, str]:
    rows = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m:
            # Markdown code spans around a placeholder (`{name}`) are formatting only.
            rows[m.group(1)] = m.group(2).replace("`", "")
    return rows


def test_every_row_is_in_copy_verbatim() -> None:
    table = _table()
    assert set(table) == {f"C{n}" for n in (*range(1, 24), 26, 27, 28)}
    assert table == copy.TABLE


def test_labels_are_derived_from_their_strings() -> None:
    assert copy.C11.startswith(copy.NOT_EXERCISED + ":")
    assert copy.C13.startswith(copy.L2_NOT_ASSESSED + ":")
    assert copy.C14.startswith(copy.FALSE_ALARM + ":")
    for n, meaning in enumerate(copy.LEVEL_MEANINGS):
        assert meaning.startswith(f"L{n} ")


def test_no_fixed_string_says_fixed() -> None:
    texts = [v for k, v in vars(copy).items() if k.isupper() and isinstance(v, str)]
    texts += list(copy.FACT_PHRASES.values()) + list(copy.HERO_PHRASES) + list(copy.SIGNAL_PHRASES.values())
    for t in texts:
        assert not re.search(r"\bfixed\b", t, re.IGNORECASE), t
