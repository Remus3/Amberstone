"""The RM-111 ARAM item-interaction snapshot must survive a clean checkout.

WHY THIS FILE EXISTS
    ``dashboard/_deterministic_coaching.py:1306-1322`` sources the deterministic
    ``item_build_reasons`` map from
    ``core.aram_item_interaction_context.item_interaction_cues``, which reads
    ``data/coaching/aram_item_interaction.json``. That artifact used to be
    gitignored, so the coverage the Haiku-elimination program depends on existed
    ONLY on the machine that ran the precompute.

    The degrade is SILENT by construction, at three stacked fail-soft layers:
      * ``aram_item_interaction_context._load_index`` returns ``{}`` on OSError
        (absent file) - core/aram_item_interaction_context.py:139-141.
      * ``item_interaction_cues`` returns ``{}`` when the index is empty -
        core/aram_item_interaction_context.py:274-276.
      * the dashboard call site swallows every exception into ``cue_reasons =
        {}`` - dashboard/_deterministic_coaching.py:1321-1322.
    Nothing logs, nothing raises, and the tick still renders. A machine without
    the artifact produces an EMPTY reason map that looks like "this comp shape
    has no evidence" rather than "the corpus is missing".

    Every pre-existing test over this surface
    (``tests/test_aram_item_interaction.py``,
    ``tests/test_aram_item_interaction_context.py``,
    ``tests/test_aram_coach_item_interaction_wiring.py``,
    ``tests/test_aram_shadow_field_parity.py``) drives the module through the
    ``_load_index(path=...)`` / ``_INDEX`` fixture seam, so all of them keep
    passing with the real artifact absent. That is the gap this file closes.

WHAT IS ASSERTED
    The artifact is git-TRACKED and therefore present in a clean checkout, and
    the REAL default read path (no fixture, no monkeypatched path) yields
    non-sentinel cues. Every expectation is read off disk - the on-disk
    ``.gitignore`` text, the on-disk snapshot's own cells, the git index - never
    a constant copied into this file
    (``feedback_contract_test_must_read_the_contract_from_disk``).

DECISION RECORD (measured 2026-07-30)
    Tracking beats regeneration here. The precompute's sole input is
    ``data/rewind_history.db``, 1,870,598,144 bytes and gitignored at
    ``.gitignore:32`` (``**/*.db``) as a personal match corpus, so a clean
    checkout can never regenerate the snapshot. The snapshot itself is 300,745
    bytes of pure-ASCII aggregate statistics (776 cells, zero identifiers) and a
    re-run over an unchanged corpus is byte-identical - sha256 5aa4d89a8430a77d
    both times. ``tools/aram_item_interaction_precompute.py`` stays the tracked
    refresh path.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from core import aram_item_interaction_context as ctx
from core.aram_comp_verdict import compute_factors
from core.aram_item_interaction import DEFAULT_TIMING_BUCKETS, shape_from_factors

_ROOT = Path(__file__).resolve().parent.parent
_REL = "data/coaching/aram_item_interaction.json"
_SNAPSHOT = _ROOT / _REL


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", *args), cwd=str(_ROOT), capture_output=True, text=True, timeout=60
    )


def _raw() -> dict:
    """The on-disk snapshot, or a hard failure naming the missing path."""
    if not _SNAPSHOT.exists():
        pytest.fail(
            f"{_REL} is absent from this checkout. It is the deterministic "
            "item_build_reasons corpus and must be tracked, not machine-local."
        )
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture()
def real_default_index():
    """Force the loader onto its REAL default path for one test.

    The module memoises ``_INDEX`` and sibling test files overwrite it with tmp
    fixtures, so this clears it before and after rather than trusting whatever
    the worker happened to load first.
    """
    saved = ctx._INDEX
    ctx._INDEX = None
    try:
        yield
    finally:
        ctx._INDEX = saved


def test_snapshot_path_is_not_gitignored():
    """No .gitignore line may exclude the snapshot.

    Reads the ignore file off disk and looks for the literal path plus the
    obvious directory-level wildcards that would swallow it, instead of pinning
    a line number that a later edit would silently invalidate.
    """
    text = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    offenders = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            continue
        pattern = stripped.lstrip("/")
        if pattern in (_REL, "aram_item_interaction.json"):
            offenders.append((lineno, stripped))
            continue
        if re.fullmatch(r"data/coaching/?\*?\*?/?\*?", pattern):
            offenders.append((lineno, stripped))
    assert not offenders, (
        f".gitignore still excludes {_REL}: {offenders}. The deterministic "
        "item_build_reasons corpus cannot be machine-local."
    )


def test_snapshot_is_git_tracked():
    """The snapshot is in the git index, i.e. a fresh clone gets it."""
    listed = _git("ls-files", "--", _REL)
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.strip() == _REL, (
        f"git does not track {_REL} (ls-files -> {listed.stdout!r}). A clean "
        "checkout would have zero item-interaction coverage."
    )
    ignored = _git("check-ignore", "--", _REL)
    assert ignored.returncode != 0, (
        f"git check-ignore still matches {_REL}: {ignored.stdout.strip()!r}"
    )


def test_regen_path_is_git_tracked():
    """The refresh script survives a clean checkout too."""
    rel = "tools/aram_item_interaction_precompute.py"
    listed = _git("ls-files", "--", rel)
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.strip() == rel, f"git does not track {rel}"


def test_snapshot_schema_matches_consumer_and_producer():
    """On-disk schema string agrees with both ends of the contract."""
    import sys

    tools = _ROOT / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    import aram_item_interaction_precompute as precompute

    on_disk = _raw().get("schema")
    assert on_disk == ctx.SCHEMA, (on_disk, ctx.SCHEMA)
    assert on_disk == precompute.SCHEMA, (on_disk, precompute.SCHEMA)


def test_snapshot_is_ascii_and_carries_no_identifiers():
    """A now-tracked artifact must satisfy the repo ASCII rule and carry no PII."""
    raw_bytes = _SNAPSHOT.read_bytes() if _SNAPSHOT.exists() else b""
    if not raw_bytes:
        pytest.fail(f"{_REL} is absent from this checkout")
    raw_bytes.decode("ascii")  # raises on any non-ASCII byte
    lowered = raw_bytes.decode("ascii").lower()
    for token in ("puuid", "summonername", "riotidgamename", "na1_", "c:\\", "/users/"):
        assert token not in lowered, f"snapshot leaks {token!r}"


def test_default_path_index_is_populated(real_default_index):
    """``_load_index()`` with NO path argument builds a usable index.

    This is the exact call ``_get_index`` makes on a live tick. Sibling tests
    only ever exercise ``_load_index(path=tmp)``, so this is the first assertion
    that the SHIPPED default resolves to real data.
    """
    index = ctx._load_index()
    assert index, (
        f"_load_index() over the default path is empty; {_REL} exists="
        f"{_SNAPSHOT.exists()}"
    )
    cells = _raw().get("cells") or []
    assert len(index.get("by_id") or {}) >= len(cells) // 2
    assert index.get("provenance")


def test_real_snapshot_yields_non_sentinel_cues(real_default_index):
    """Unmocked end-to-end: the tracked corpus produces real reason strings.

    Inputs are DERIVED from the snapshot on disk. An empty enemy list resolves
    to whatever shape ``compute_factors([])`` implies, so the cells for that
    shape are selected off disk and their timing bucket is turned back into a
    ``game_time_s`` inside the band. The assertion mirrors
    ``dashboard/_deterministic_coaching.py:1316-1320``, which DROPS
    ``CUE_SENTINEL`` - so a sentinel-only result is the same zero coverage as an
    absent file.
    """
    empty_shape = shape_from_factors(compute_factors([]))
    cells = [
        c for c in (_raw().get("cells") or [])
        if isinstance(c, dict) and c.get("shape") == empty_shape
        and isinstance(c.get("name"), str) and c.get("name")
    ]
    assert cells, f"snapshot carries no {empty_shape} cells to drive the check"

    bands = {label: (lo, hi) for label, lo, hi in DEFAULT_TIMING_BUCKETS}
    by_timing: dict[str, list[str]] = {}
    for cell in cells:
        timing = cell.get("timing")
        if timing in bands:
            by_timing.setdefault(timing, []).append(cell["name"])
    assert by_timing, "no snapshot cell used a known timing bucket"

    checked = 0
    for timing, names in sorted(by_timing.items()):
        lo, hi = bands[timing]
        game_time_s = float(lo) + 1.0 if hi is None else (float(lo) + float(hi)) / 2.0
        cues = ctx.item_interaction_cues(
            [], game_time_s, sorted(set(names)), game_mode="ARAM"
        )
        assert cues, f"no cues at all for timing={timing}"
        real = {k: v for k, v in cues.items() if v != ctx.CUE_SENTINEL}
        assert real, (
            f"every cue for timing={timing} shape={empty_shape} was the "
            f"sentinel {ctx.CUE_SENTINEL!r}; that is zero deterministic "
            "item_build_reasons coverage"
        )
        checked += len(real)
    assert checked >= len(by_timing)


def test_deterministic_item_build_reasons_are_non_empty_from_tracked_corpus(
    real_default_index,
):
    """The dashboard's own filter, applied to the real corpus, keeps entries.

    Replays ``dashboard/_deterministic_coaching.py:1312-1320`` verbatim over the
    tracked snapshot and asserts the surviving map is non-empty, then feeds it
    through ``core.aram_deterministic_coach.build_block`` - the function that
    actually emits ``item_build_reasons`` - so the assertion lands on the
    shipped field rather than on an intermediate dict.
    """
    from core.aram_deterministic_coach import build_block

    empty_shape = shape_from_factors(compute_factors([]))
    bands = {label: (lo, hi) for label, lo, hi in DEFAULT_TIMING_BUCKETS}
    names_by_timing: dict[str, list[str]] = {}
    for cell in (_raw().get("cells") or []):
        if not isinstance(cell, dict) or cell.get("shape") != empty_shape:
            continue
        timing, name = cell.get("timing"), cell.get("name")
        if timing in bands and isinstance(name, str) and name:
            names_by_timing.setdefault(timing, []).append(name)
    assert names_by_timing

    timing = sorted(names_by_timing)[0]
    lo, hi = bands[timing]
    game_time_s = float(lo) + 1.0 if hi is None else (float(lo) + float(hi)) / 2.0
    build_order = sorted(set(names_by_timing[timing]))

    raw_cues = ctx.item_interaction_cues(
        [], game_time_s, build_order, game_mode="ARAM"
    )
    cue_reasons = {
        str(k): v for k, v in (raw_cues or {}).items()
        if isinstance(v, str) and v.strip() and v.strip() != ctx.CUE_SENTINEL
    }
    assert cue_reasons, (
        "the dashboard sentinel filter emptied the reason map over the tracked "
        "corpus - deterministic item_build_reasons would be {} on every tick"
    )

    block = build_block(
        80.0,
        build_order=build_order,
        item_build_reasons=cue_reasons,
    )
    reasons = block.get("item_build_reasons")
    assert isinstance(reasons, dict) and reasons, block
    assert set(cue_reasons).issubset(set(reasons))
