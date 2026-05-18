"""Round 27 - dashboard KDA streaks strip."""
from __future__ import annotations

from pathlib import Path


def test_html_contains_streaks_scaffold() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    assert 'id="adapt-streaks"' in html
    assert 'id="streaks-hot"' in html
    assert 'id="streaks-cold"' in html
    assert "KDA streaks" in html
