"""
tests/snapshot_panels/test_lobby_leader_tag_retired.py
S144-U-252 (s144 uiux): the dead .lobby-view-leader-tag rule is retired.

THE DEFECT. web/css/panels/header.css carried a .lobby-view-leader-tag rule
(--clock on --gold-soft, --fs-xs 16 px / 800, a 999px pill) that nothing in
web/ renders. Its only emitter was the hidden #lv-leader-tag stub in
web/index.html, which the E11 lobby pass removed (the index.html comment
beside the mode menu records it; docs/qa/LOBBY_QA_2026-07-04.md row D4).
Since then the party leader is drawn by the member-row crown
(.lv-member-leader-crown in web/js/main.js), so the pill rule was a second,
unreachable leader mark for every contrast and token audit to measure - the
S144-U-251 audit read it as --clock on --gold-soft at 16 px, the same pair
that failed AA on the mode menu, and filed it as dead instead of fixing it.

THE FIX. The rule is removed, as S144-U-248 removed the dead friends-row
rules. Static: no browser is needed to prove a selector has no emitter.
"""
from pathlib import Path

from tests import _css_split

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
_TOKEN = "lobby-view-leader-tag"


def _web_files(suffixes):
    return sorted(p for p in WEB.rglob("*")
                  if p.is_file() and p.suffix in suffixes)


def test_nothing_in_web_emits_the_leader_tag():
    """Tripwire: if a leader pill is wired back up, author and measure its
    rule fresh (the --clock / --gold-soft pair needs the S144-U-251 lift)."""
    files = _web_files({".js", ".mjs", ".html", ".json"})
    assert any(p.name == "main.js" for p in files), "main.js not enumerated"
    assert any(p.name == "index.html" for p in files), "index.html not enumerated"
    producers = [str(p.relative_to(ROOT)) for p in files
                 if _TOKEN in p.read_text(encoding="utf-8", errors="ignore")]
    assert producers == [], producers


def test_leader_tag_rule_is_gone_from_web_css():
    css_files = _web_files({".css"})
    assert len(css_files) > 20, "CSS enumeration found almost nothing"
    hits = []
    for path in css_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            if "." + _TOKEN in line:
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert hits == [], hits


def test_party_leader_is_still_marked_by_the_crown():
    """The retirement takes no live leader mark with it: the member row
    still emits the crown, and its rule is still in the header.css family."""
    js = (WEB / "js" / "main.js").read_text(encoding="utf-8")
    assert "lv-member-leader-crown" in js, "member-row leader crown gone"
    assert "lv-crown-img" in js, "crown image markup gone"
    css = _css_split.family_text("web/css/panels/header.css")
    assert ".lv-crown-img" in css, ".lv-crown-img rule missing"


def test_this_file_is_ascii_lf():
    raw = Path(__file__).read_bytes()
    assert all(b < 0x80 for b in raw), "non-ASCII byte in this test file"
    assert b"\r" not in raw, "CR byte in this test file"
