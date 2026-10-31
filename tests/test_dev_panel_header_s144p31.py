"""RM-1182 - the line-1 header of web/js/panels/dev.js names only what the
module still does.

WHY. Line 1 is the one-line role statement a reader meets first. It said
"Dev panel - settings, dev/sim fixture viewer, replay scrubber." for months
after the Dev / Sim Preview block (_devRenderFixtures, #dev-fixtures-body,
fetch of /api/sim/_manifest) was deleted in 824c79c44 (s218). RM-339
(04cfe5247) later removed the dead Diagnostics block and dropped
"diagnostics" from the same line, but kept "dev/sim fixture viewer", so the
header described a feature with no code behind it. Nothing reads a comment,
so only a test that ties each named feature to a live symbol keeps it honest.

WHAT IS PINNED.
  1. Every feature the header names maps to a function DEFINED in dev.js
     (FEATURES below). Delete the feature and keep the header -> red.
  2. The header names none of the removed features (REMOVED below).
  3. The removed sim-preview identifiers stay out of web/js and
     web/index.html, so the feature cannot come back half-wired behind an
     honest header.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEV_JS = REPO / "web" / "js" / "panels" / "dev.js"

# Header phrase (case-insensitive) -> the function that implements it.
FEATURES = {
    "settings view": "_settingsRefresh",
    "spend gates": "renderSpendGates",
    "replay scrubber": "_replayViewRefresh",
    "past-match minimap": "_replayMapDraw",
}

# Phrases for features that no longer exist in this module.
REMOVED = ("sim", "fixture viewer", "diagnostics")

# Identifiers of the Dev / Sim Preview block deleted in 824c79c44.
SIM_PREVIEW_IDENTIFIERS = (
    "_devRenderFixtures",
    "dev-fixtures-body",
    "dev-fixture-count",
    "/api/sim/_manifest",
)


def _header() -> str:
    first = DEV_JS.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("// Dev panel - "), (
        f"web/js/panels/dev.js line 1 is not the module header: {first!r}"
    )
    return first


def test_every_named_feature_has_a_defined_function() -> None:
    header = _header().lower()
    src = DEV_JS.read_text(encoding="utf-8")
    for phrase, symbol in FEATURES.items():
        assert phrase in header, (
            f"dev.js header no longer names {phrase!r}; if the feature moved, "
            f"update FEATURES here together with the header: {header!r}"
        )
        assert re.search(rf"^function {re.escape(symbol)}\(", src, re.M), (
            f"dev.js header names {phrase!r} but defines no {symbol}(); "
            "drop the phrase from line 1 (and from FEATURES) if the feature "
            "is gone"
        )


def test_header_names_no_removed_feature() -> None:
    header = _header().lower()
    for phrase in REMOVED:
        assert not re.search(rf"\b{re.escape(phrase)}\b", header), (
            f"dev.js header names {phrase!r}, a feature this module no longer "
            f"has: {header!r}"
        )


def test_sim_preview_identifiers_stay_removed() -> None:
    targets = sorted((REPO / "web" / "js").rglob("*.js"))
    targets += sorted((REPO / "web" / "js").rglob("*.mjs"))
    targets.append(REPO / "web" / "index.html")
    assert len(targets) > 20, "web/js walk found too few files to mean anything"
    hits = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for ident in SIM_PREVIEW_IDENTIFIERS:
            if ident in text:
                hits.append(f"{path.relative_to(REPO).as_posix()}: {ident}")
    assert not hits, (
        "The Dev / Sim Preview block was deleted in 824c79c44; confirm a real "
        f"consumer exists before bringing it back: {hits}"
    )
