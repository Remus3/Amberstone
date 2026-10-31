"""RM-1053 part (s144 lane ds cycle 124) - the RM-98 spec is cited by section.

``docs/specs/SPEC_rm98_cast_rate_time_base.md`` was adjudicated at 4c76993e2.
The ENGINE 1.244.0 build (d6894db3d) then prepended a 29-line "Build note" to
it, in the same commit that added ``cast_propensity.py``. Every ``SPEC:<n>``
line cite into it written for that build was therefore off by 29 lines from
the start: ``SPEC:135-147`` (the Recommendation) now lands in correction 4
and the Both-fixes section, ``SPEC:91-99`` (correction 2) lands in
correction 1, and so on.

This guard fences the five DS files that cited the spec by line. They now
name a section heading or a numbered correction plus its title, and the
facts the prose restates are pinned to the section that holds them, so a
future spec edit that moves a fact fails here instead of rotting silently.

Out of scope on purpose: ``cast_propensity.py`` also cites
``SPEC_rm39_rm43_ability_haste.md:174-176``, a different spec, and that cite
was measured correct at this cycle (the "better denominator, not a
correction factor" sentence). Dated records (docs/ROADMAP_HISTORY.md, the
LEDGER, history notes) are not swept.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DS = REPO / "agents" / "daemon_slayer"
SPEC = REPO / "docs" / "specs" / "SPEC_rm98_cast_rate_time_base.md"

# A bare ``SPEC:<n>`` (the RM-98 spec's in-repo shorthand) or the spec's own
# file name followed by a line number.
_SPEC_LINE_CITE = re.compile(
    r"\bSPEC:\d|SPEC_rm98_cast_rate_time_base\.md:\d"
)

CORRECTIONS = {
    1: "The defect is already shipped and DEFAULT-ON",
    2: "The term is NOT inert",
    3: "The 27x headline overstates",
    4: "RM-98 is under-scoped",
}
RECOMMENDATION = "``## Recommendation``"
BOTH_FIXES = "Both fixes the RM-39 spec named are unavailable"
VERDICT = "``## Verdict``"

# file -> (corrections cited, other section anchors cited)
TARGETS = {
    DS / "cast_propensity.py": ((2, 3, 4), (RECOMMENDATION, BOTH_FIXES)),
    DS / "onhit_dps.py": ((1, 3, 4), (BOTH_FIXES,)),
    DS / "_ad_axis_ability.py": ((1, 2), ()),
    DS / "hybrid.py": ((4,), (BOTH_FIXES,)),
    DS / "tests" / "test_cast_propensity_prior_rm98.py": (
        (4,),
        (RECOMMENDATION, VERDICT),
    ),
}


def _flat(path: Path) -> str:
    """Whitespace-normalised text with ``#`` comment markers dropped, so a
    phrase wrapped across docstring or comment lines still matches."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return " ".join(
        " ".join(re.sub(r"^\s*#\s?", "", line).split()) for line in lines
    )


def _spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def _heading_section(title: str) -> str:
    """Body of the ``## <title>...`` section, up to the next ``## ``."""
    text = _spec()
    start = text.index("\n## " + title)
    end = text.find("\n## ", start + 1)
    return text[start: end if end != -1 else len(text)]


def _correction(n: int) -> str:
    """Body of numbered correction ``n`` in the Four-corrections section."""
    section = _heading_section("Four corrections to RM-98 as filed")
    start = section.index(f"**{n}. ")
    nxt = section.find(f"**{n + 1}. ", start)
    return section[start: nxt if nxt != -1 else len(section)]


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "(SPEC:91-99)",
        "NOT WIRED (SPEC:109-114, deliberate",
        "``docs/specs/SPEC_rm98_cast_rate_time_base.md:135-147``",
        "signal, SPEC:144-147)",
    ):
        assert _SPEC_LINE_CITE.search(sample), sample
    for sample in (
        "``SPEC_rm39_rm43_ability_haste.md:174-176``",
        "``docs/specs/SPEC_rm98_cast_rate_time_base.md``",
        'SPEC correction 2 ("The term is NOT inert")',
        "the SPEC ``## Recommendation``",
    ):
        assert not _SPEC_LINE_CITE.search(sample), sample


def test_targets_exist():
    missing = [str(p.relative_to(REPO)) for p in TARGETS if not p.is_file()]
    assert not missing, missing


def test_no_rm98_spec_line_cite_left():
    hits = [
        f"{path.name}:{i}: {line.strip()}"
        for path in TARGETS
        for i, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        )
        if _SPEC_LINE_CITE.search(line)
    ]
    assert not hits, "cite the RM-98 spec by section:\n" + "\n".join(hits)


def test_targets_name_their_sections():
    missing = []
    for path, (corrections, anchors) in TARGETS.items():
        flat = _flat(path)
        for n in corrections:
            for needle in (f"correction {n}", CORRECTIONS[n]):
                if needle not in flat:
                    missing.append(f"{path.name}: {needle}")
        missing.extend(
            f"{path.name}: {a}" for a in anchors if a not in flat
        )
    assert not missing, missing


def test_cited_sections_exist_in_the_spec():
    text = _spec()
    for n, title in CORRECTIONS.items():
        assert f"**{n}. {title}" in text, (n, title)
    assert "\n## Recommendation\n" in text
    assert "\n## " + BOTH_FIXES in text
    assert "\n## Verdict" in text


def test_restated_facts_live_in_the_cited_section():
    # correction 1: the plain sum ships DEFAULT-ON in ds.onhit (onhit_dps
    # says the spec names its own sum as the shipped instance).
    c1 = _correction(1)
    assert "DEFAULT-ON" in c1 and "ds.onhit" in c1
    # correction 2: the load-bearing shares cast_propensity and
    # _ad_axis_ability restate.
    c2 = _correction(2)
    for fact in ("30.5%", "29.2%", "65.9%"):
        assert fact in c2, fact
    # correction 3: the ~7x characteristic distortion.
    assert "~7x" in _correction(3)
    # correction 4: the six mixed-basis champions and the unwired consumers.
    c4 = _correction(4)
    for fact in ("Aphelios, Katarina, Kled,", "item_proc_dps", "hps.py"):
        assert fact in c4, fact
    # Both fixes: the 1.25x lift and the 60s frame cadence.
    both = _heading_section(BOTH_FIXES)
    for fact in ("1.25x", "60016-60021"):
        assert fact in both, fact
    # Recommendation: the prior and the must-not-discard Aatrox W signal.
    rec = _heading_section("Recommendation")
    for fact in ("cast-propensity prior", "must-not-discard", "Infernal Chains"):
        assert fact in rec, fact
    # Verdict: the Veigar Q figure the propensity test reproduces.
    verdict = _heading_section("Verdict")
    for fact in ("Veigar Q has 4s base cooldown", "0.098 casts/sec"):
        assert fact in verdict, fact
