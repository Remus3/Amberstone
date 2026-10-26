"""Guard (RM-921): the DS doc's brawl_coach reachability paragraph stays true.

``docs/DAEMON_SLAYER.md`` carries the "``brawl_coach.py`` is live-reachable"
paragraph that the CLAUDE.md Settled line leans on (never delete the coach as
dead code). Measured 2026-10-26, it had rotted in three ways:

* four ``file:line`` citations no longer pointed at what the prose claims
  (``core/game_snapshot.py:98-102`` landed on a docstring, the
  ``app/_game_lifecycle.py`` loader and the ``brawl_coach.py`` Haiku call had
  moved, and ``BACKLOG.md:124`` had become an unrelated row);
* it said the rotating modes route to ``MODE_BRAWL`` "not only for Brawl",
  but since the 2026-08-11 compliance gate Riot's own ``BRAWL`` game mode is
  in ``FORBIDDEN_GAME_MODES`` and returns ``MODE_UNSUPPORTED``;
* it said two other docs "carry the same wrong label", but both were
  corrected on 2026-08-06.

Every citation in the paragraph must cover the exact code line its claim rests
on (an exact substring, never a prose heuristic, so a red here is always a real
drift), the claims are re-checked behaviourally, and the refuted phrasings may
not return. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core import coach_registry
from core.game_snapshot import (
    FORBIDDEN_GAME_MODES,
    MODE_BRAWL,
    MODE_UNSUPPORTED,
    mode_from_game_mode_string,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_OPENER = "**`brawl_coach.py` is live-reachable"

# path -> the exact code substrings one cited range of that path must cover.
# A path may be cited more than once (game_snapshot: the forbidden gate and the
# MODE_BRAWL branch); each anchor must be covered by at least one citation.
_ANCHORS = {
    "core/game_snapshot.py": (
        'FORBIDDEN_GAME_MODES = ("BRAWL"',
        "return MODE_BRAWL",
    ),
    "app/__init__.py": ("self._brawl_mode = (mode == MODE_BRAWL)",),
    "core/coach_registry.py": ('"_brawl_mode": ("coaches.brawl_coach"',),
    "app/_game_lifecycle.py": (
        "MODE_COACH_MAP as cmap",
        "importlib.import_module(mp)",
    ),
    "config/feature_flags.json": ('"brawl": {',),
    "coaches/brawl_coach.py": ("self._client.messages.create(",),
}

# Non-unique lines, located as "the line right after this anchor"; the cited
# range must cover them too.
_FOLLOWERS = {
    "config/feature_flags.json": ('"brawl": {', '"live_coaching": "allow"'),
}

_CITE = re.compile(r"`([A-Za-z0-9_./-]+\.[a-z]+):(\d+)(?:-(\d+))?`")


def _paragraph() -> str:
    text = _DOC.read_text(encoding="utf-8")
    start = text.index(_OPENER)
    end = text.index("\n## ", start)
    return text[start:end]


def _citations() -> list[tuple[str, int, int]]:
    return [
        (m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)))
        for m in _CITE.finditer(_paragraph())
    ]


def _lines(rel: str) -> list[str]:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()


def test_paragraph_cites_only_anchored_paths():
    cited = {path for path, _, _ in _citations()}
    assert cited == set(_ANCHORS), (
        "the brawl paragraph's backticked file:line citations changed; add an "
        "anchor for a new one or drop a stale one: "
        f"cited={sorted(cited)} anchored={sorted(_ANCHORS)}"
    )


def test_every_anchor_is_covered_by_a_citation():
    cites = _citations()
    misses = []
    for path, anchors in _ANCHORS.items():
        lines = _lines(path)
        ranges = [(a, b) for p, a, b in cites if p == path]
        for anchor in anchors:
            hit = [n for n, line in enumerate(lines, 1) if anchor in line]
            assert len(hit) == 1, f"{path}: anchor {anchor!r} found {hit}"
            if not any(a <= hit[0] <= b for a, b in ranges):
                misses.append(f"{path}:{hit[0]} ({anchor}) not in {ranges}")
    for path, (anchor, follower) in _FOLLOWERS.items():
        lines = _lines(path)
        n = [i for i, line in enumerate(lines, 1) if anchor in line][0] + 1
        assert follower in lines[n - 1], f"{path}:{n} is not {follower!r}"
        if not any(a <= n <= b for p, a, b in cites if p == path):
            misses.append(f"{path}:{n} ({follower}) not cited")
    assert not misses, "stale citations in the brawl paragraph:\n" + "\n".join(misses)


def test_no_citation_range_is_padded():
    # A citation spanning far more than its anchors would pass the coverage
    # test while pointing a reader at unrelated code.
    for path, a, b in _citations():
        assert b - a <= 20, f"{path}:{a}-{b} spans {b - a + 1} lines"


def test_listed_rotating_modes_route_to_brawl():
    para = _paragraph()
    listed = re.findall(r"`([A-Z]+)`", para.split("returns `MODE_BRAWL` for", 1)[1].split(".", 1)[0])
    branch = [n for n, line in enumerate(_lines("core/game_snapshot.py"), 1)
              if "return MODE_BRAWL" in line][0]
    source = "\n".join(_lines("core/game_snapshot.py")[branch - 5:branch])
    in_source = set(re.findall(r'"([A-Z]+)"', source))
    assert set(listed) == in_source, (listed, in_source)
    for gm in listed:
        assert mode_from_game_mode_string(gm) == MODE_BRAWL, gm


def test_riot_brawl_itself_is_refused_not_routed():
    assert "BRAWL" in FORBIDDEN_GAME_MODES
    assert mode_from_game_mode_string("BRAWL") == MODE_UNSUPPORTED
    para = _paragraph()
    assert "not only for Brawl" not in para
    assert "`MODE_UNSUPPORTED`" in para


def test_registry_and_policy_claims_hold():
    assert coach_registry.MODE_COACH_MAP["_brawl_mode"][0] == "coaches.brawl_coach"
    assert coach_registry.MODE_POLICY_MAP["_brawl_mode"] == ("brawl", "live_coaching")
    flags = json.loads((_REPO_ROOT / "config" / "feature_flags.json").read_text(encoding="utf-8"))
    assert flags["brawl"]["live_coaching"] == "allow"


def _flat(text: str) -> str:
    # Phrase checks must survive a reflow or a capitalisation change.
    return " ".join(text.split()).lower()


def test_refuted_phrasings_do_not_return():
    para = _paragraph()
    flat = _flat(para)
    for phrase in (
        "carry the same wrong label",
        "not only for brawl",
        "five other game modes",
        "every rotating game mode",
    ):
        assert phrase not in flat, phrase
    assert not re.search(r"BACKLOG\.md:\d", para), "cite the BACKLOG row by name; its line numbers churn"
    assert "corrected on 2026-08-06" in flat
    for rel in ("ops/audit/HZ_HAIKU_CALL_INVENTORY.md", "docs/specs/RM-141_JADE_MODE.md"):
        assert "corrected 2026-08-06" in _flat((_REPO_ROOT / rel).read_text(encoding="utf-8")), rel


def test_backlog_row_carries_the_cited_patch():
    para = _flat(_paragraph())
    assert '"brawl mode re-enable" row in `backlog.md`' in para
    rows = [line for line in (_REPO_ROOT / "BACKLOG.md").read_text(encoding="utf-8").splitlines()
            if "**Brawl mode re-enable**" in line]
    assert len(rows) == 1, rows
    assert "patch 25.23" in rows[0] and "patch 25.23" in para


def test_paragraph_is_ascii():
    _paragraph().encode("ascii")
