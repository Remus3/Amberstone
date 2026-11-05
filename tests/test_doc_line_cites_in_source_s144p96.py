"""RM-1396 - seven source modules cite docs and scripts by name, not by line.

Measured 2026-11-04 over every tracked non-test, non-DS .py: besides the
module-to-module cites earlier slices fixed, source comments still pointed at
a Markdown doc or a script by LINE, and the lines had moved:

- coaches/aram_coach.py and coaches/arena_coach.py cited "BACKLOG.md:59" for
  the same-state Haiku-skip debounce; line 59 of BACKLOG.md is an unrelated
  row now (the debounce is LEDGER items 506 and 507).
- core/precomputed_laning_coach.py cited HZ_HAIKU_CALL_INVENTORY.md:49-108 and
  :92-95; the doc names those places by heading and bullet.
- core/vision_fusion.py cited docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163 next to
  the sentence it quotes (the quote is the anchor).
- core/smoothed_rates_101qq.py cited the source() fence as BACKLOG.md:126;
  that line is blank now (the fence is the RM-295a BACKLOG row).
- ops/rc_transactional_deploy.py cited scripts/bootstrap_dev.ps1:105 and
  ops/rc_league_watcher.ps1:88 for the directory lists that create
  deploy_requests.
- tools/unresolved_token_scan.py cited ROADMAP.md:305; the RM-108 premise is
  recorded in LEDGER item 966.

Each now names the section, bullet, quoted sentence or list entry. This pins
(a) no `<file>.md|.ps1:<n>` cite returns to the seven modules, (b) each named
anchor still exists in its target, (c) the module still names it, (d) the
cite pattern still bites the old forms and spares the new ones. Left on
purpose: tools/stop_claim_gate.py and tools/drift_guard.py (they quote a cite
as the pattern they detect), tools/citation_audit.py (cites are its subject),
dashboard routes other lanes changed, and ops/launcher/* (main session owns).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

MODULES = (
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "core/precomputed_laning_coach.py",
    "core/vision_fusion.py",
    "core/smoothed_rates_101qq.py",
    "ops/rc_transactional_deploy.py",
    "tools/unresolved_token_scan.py",
)

# A doc or script cited by position: "x.md:12", "x.md:12-15", "x.ps1:105".
_LINE_CITE = re.compile(r"[\w./\\-]+\.(?:md|ps1):\d+")


def _read(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8")


# (module, the prose it must still carry)
NEW_PROSE = (
    ("coaches/aram_coach.py", "debounce (LEDGER item 506)"),
    ("coaches/arena_coach.py", "debounce (LEDGER item 507)"),
    ("core/precomputed_laning_coach.py",
     'the "UPDATE 2026-06-19 (run 2026-06-19-01)"'),
    ("core/precomputed_laning_coach.py", 'the "Root cause (confusion matrix"'),
    ("core/vision_fusion.py", 'docs/NO_LLM_PRECOMPUTE_PLAN.md ("Fuse Live'),
    ("core/smoothed_rates_101qq.py", "the fence the RM-295a BACKLOG row records"),
    ("ops/rc_transactional_deploy.py", "directory list in"),
    ("tools/unresolved_token_scan.py", "LEDGER item 966 records the premise"),
)

# (file the anchor must be IN, anchor text)
ANCHORS = (
    ("docs/LEDGER.md", "\n506. DONE "),
    ("docs/LEDGER.md", "\n507. DONE "),
    ("docs/LEDGER.md", "\n966. DONE "),
    ("ops/audit/HZ_HAIKU_CALL_INVENTORY.md",
     "## UPDATE 2026-06-19 (run 2026-06-19-01)"),
    ("ops/audit/HZ_HAIKU_CALL_INVENTORY.md", "Root cause (confusion matrix"),
    ("docs/NO_LLM_PRECOMPUTE_PLAN.md",
     "Fuse Live Client API (high trust) + CV reads (confidence-weighted)"),
    ("BACKLOG.md", "RM-295a"),
    ("scripts/bootstrap_dev.ps1", "deploy_requests"),
    ("ops/rc_league_watcher.ps1", '"deploy_requests"'),
)


@pytest.mark.parametrize("rel", MODULES)
def test_module_cites_no_doc_by_line(rel):
    hits = _LINE_CITE.findall(_read(rel))
    assert not hits, f"{rel} cites by line again: {hits} (RM-1396)"


@pytest.mark.parametrize("rel", MODULES)
def test_module_is_ascii_and_lf(rel):
    raw = (ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", MODULES)
def test_module_compiles_without_a_syntax_warning(rel):
    """A path written with backslashes in a docstring is an invalid escape."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(_read(rel), rel, "exec")


@pytest.mark.parametrize(("rel", "prose"), NEW_PROSE)
def test_module_still_names_its_anchor(rel, prose):
    assert prose in _read(rel), f"{rel} lost {prose!r}"


@pytest.mark.parametrize(("rel", "anchor"), ANCHORS)
def test_anchor_still_exists_in_its_target(rel, anchor):
    assert anchor in _read(rel), f"{rel} no longer carries {anchor!r}; re-point"


def test_pattern_catches_the_old_forms_and_spares_the_new():
    for probe in ("(BACKLOG.md:59)", "HZ_HAIKU_CALL_INVENTORY.md:49-108",
                  "docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163",
                  "`scripts/bootstrap_dev.ps1:105`", "ROADMAP.md:305"):
        assert _LINE_CITE.search(probe), probe
    for probe in ("(LEDGER item 506)", "docs/NO_LLM_PRECOMPUTE_PLAN.md (\"Fuse",
                  "BACKLOG.md RM-295a row", "scripts/bootstrap_dev.ps1,"):
        assert not _LINE_CITE.search(probe), probe
