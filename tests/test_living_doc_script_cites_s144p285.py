"""S144-P-285 - a living docs/*.md never names a repo script that no longer exists as if it were live.

Sibling of test_command_doc_script_cites_s144p284 (tools/*.md prompts); this one covers the living docs at the
docs/ root. Measured 2026-11-06 over the 62 tracked ``docs/*.md``: two real dangling pointers, both fixed with
this guard - docs/OVERLAY_DOCTRINE.md still listed ``tools/gemini_ask.ps1`` as step 4 of the overlay ritual (the
Gemini pass was decommissioned and the script removed) and docs/OBS_CV_MINIMAP_PLAN.md row 4 said
``core/summoner_cooldowns.py`` "consumer exists" (deleted by the Riot-compliance removal, 538c61e4b).

Scope. Dated or append-only history is out (``_HISTORY_DOCS``: a record of what existed then is correct), as are
docs another owner holds (``_OTHER_OWNER``) and green-field specs whose cited modules are PLANNED
(``_PLANNED_SPECS``). Every other doc is scanned with the p284 scanner: a cite of an untracked
``<top-dir>/<path>.<ext>`` needs a history word within three lines, or an entry in ``_ALLOWED`` (file, path).
``_ALLOWED`` only shrinks. ``test_exempt_docs_exist`` keeps the three exempt sets from naming a vanished file.
"""
from __future__ import annotations

import subprocess

from tests._repo_walk import REPO_ROOT
from tests.test_command_doc_script_cites_s144p284 import scan_source

# Dated / append-only records: a cite of a file that existed then is history, whatever the nearby words.
_HISTORY_DOCS = frozenset({
    "docs/LEDGER.md",
    "docs/history_notes.md",
    "docs/ROADMAP_HISTORY.md",
    "docs/ORCHESTRATION_PLAN.md",
    "docs/ORCHESTRATION_PLAN_HISTORY.md",
    "docs/ORCHESTRATION_FINDINGS_ARCHIVE.md",
    "docs/_research_refill_2026-09-05.md",
})
# Held by someone else this session (read-only here): the gated lane's doc and the PKG plan.
_OTHER_OWNER = frozenset({
    "docs/LIVE_GAME_GATED_SYNC.md",
    "docs/PACKAGING_PLAN.md",
})
# Project-agnostic template (its scripts are the ones a NEW project writes) and green-field specs (their
# modules are the build plan, "do not exist yet").
_PLANNED_SPECS = frozenset({
    "docs/PORTABLE_PROJECT_CONVENTIONS.md",
    "docs/TFT_PROGRAM.md",
    "docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md",
})

# (file, cited path) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED = {
    # The note explains that the cited Game-PC agent copy is not in this tree.
    ("docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md", "tools/gamepc_lcu_agent.py"),
    # A "landed this session" snapshot of the retired DS Share mirror sync (2026-09-07 removal).
    ("docs/OVERLAY_COMPLIANCE_PLAN.md", "tools/ds_share_sync.py"),
    # "Prior pin, kept for the audit trail" lines of the main-session-owned tracker (read-only here): dated history,
    # marked only by a weak word before S144-P-287 narrowed the shared history words.
    ("docs/DS_SWEEP_TRACKER.md", "coaches/tft_pbe_coach.py"),
    ("docs/DS_SWEEP_TRACKER.md", "tft/tft_pbe_engine.py"),
}


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _living_docs(tracked: frozenset[str]) -> list[str]:
    skip = _HISTORY_DOCS | _OTHER_OWNER | _PLANNED_SPECS
    return sorted(
        p for p in tracked
        if p.startswith("docs/") and p.count("/") == 1 and p.endswith(".md") and p not in skip
    )


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _living_docs(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for _line, cited in scan_source(src, tracked):
            found.add((rel, cited))
    return found


def test_living_docs_are_enumerated():
    docs = _living_docs(_tracked())
    assert "docs/OVERLAY_DOCTRINE.md" in docs and "docs/OBS_CV_MINIMAP_PLAN.md" in docs
    assert "docs/LEDGER.md" not in docs
    assert len(docs) >= 40


def test_no_bare_cite_of_a_missing_script_in_a_living_doc():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "living doc cites a repo script that is not tracked and carries no history word within 3 lines "
        f"(say it was removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_exempt_docs_exist():
    tracked = _tracked()
    gone = sorted((_HISTORY_DOCS | _OTHER_OWNER | _PLANNED_SPECS) - tracked)
    assert not gone, f"exempt doc is not tracked any more - drop it from its set: {gone}"


def test_the_two_fixed_pointers_would_have_been_caught():
    tracked = _tracked()
    old_doctrine = (
        "4. Gemini design-director critique (`tools/gemini_ask.ps1`) on the capture;\n"
        "   take its recommendation, log it, refine.\n"
    )
    assert scan_source(old_doctrine, tracked) == [(1, "tools/gemini_ask.ps1")]
    old_row = '`core/summoner_cooldowns.py` consumer exists; drives "enemy Flash down -> all-in"\n'
    assert scan_source(old_row, tracked) == [(1, "core/summoner_cooldowns.py")]
