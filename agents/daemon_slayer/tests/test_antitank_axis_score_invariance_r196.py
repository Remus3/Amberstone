"""R196 - the axis schema lift is SCORE-INERT, pinned as a durable mutation probe.

WHY THIS MODULE EXISTS (the incident it records).

R196 added an ``axis`` field to ``AntiTankEntry``
(``"PHYSICAL"`` / ``"MAGICAL"`` / ``"BOTH"``, default ``"BOTH"``), stamped on the
31 resist-lowering (``SHRED`` / ``PERCENT_PEN``) rows across 30 champions - 22 of
which carry a non-default axis and 9 of which state ``"BOTH"`` explicitly. A
schema lift on a shipped engine dataclass is only acceptable if it moves no
score, and R196 justified itself on exactly that SCORE-INVARIANCE claim. The
claim was measured twice and both measurements were real:

  * the implementing agent digested 1368 result dicts (171 shipped champions x
    4 levels x 2 stat sets) and got the same sha256 before and after the lift;
  * a verifier subagent ran a 3-way mutation probe forcing every registry row to
    each of the three axis values, got a byte-identical 948-dict digest all three
    times, and grepped every ``.axis`` read site to prove none sat on a scoring
    path.

Neither measurement left anything on disk. The numbers lived only in a session
transcript and a ledger paragraph, so nothing stopped a later change from quietly
making ``axis`` load-bearing and no later session could re-derive the claim
without redoing the work. This module is that missing artifact: the invariance is
now a property the suite DEFENDS on every run rather than a claim someone once
made.

WHAT IS PINNED HERE, AND HOW IT DIFFERS FROM ``test_antitank_axis_r196.py``.

The sibling module already flips the axis and compares ``_mechanism_value`` - the
per-MECHANISM half. This module pins the whole-RESULT half plus the structural
half, which nothing covered:

  1. A full-output digest mutation probe. Every registry row is forced to each of
     the three legal axis values in turn and the ENTIRE ``compute_antitank``
     surface is re-digested - ``antitank_score``, ``top_kind``, ``shreds_resist``
     and every ``AntiTankSourceEntry`` field - at FULL float precision (``repr``,
     not the 4-place rounding ``to_dict`` applies, so a sub-rounding drift cannot
     hide). ``top_kind`` and ``shreds_resist`` are aggregate identities that no
     per-mechanism probe can reach.
  2. A self-check that the probe actually mutates. A mutation probe whose harness
     silently fails to mutate passes vacuously and defends nothing.
  3. The structural half: no scoring function mentions ``axis`` at all
     (``inspect.getsource``, not a text grep of the file), and no non-test module
     anywhere in the repo that references antitank reads ``.axis``. If someone
     later reads ``.axis`` in a scorer the digest probe goes red anyway - the
     structural pin is the one line that says WHY.

POPULATION - NO SAMPLING. The cross-product is the full shipped population, the
same one R196 measured: all 171 champions in the shipped
``champion_abilities.json`` (not just the 79 on the selective registry - an
unregistered champion's all-zero result is part of the contract) x levels
``(None, 1, 9, 18)`` x stats ``(None, {"ap": 300, "ad": 120})`` = 1368 result
dicts per digest, 4 digests (baseline + 3 forced axes) = 5472 computations.
Measured at ~0.03s for the whole cross-product, so no representative subset is
needed and none is taken.

INDEPENDENT RE-MEASUREMENT (2026-07-26, this module's authoring run): baseline
digest ``5f20c290dec489cdfcfc411ca62faa00078756b14ae70def80b7388ad6571766`` over
1368 dicts, byte-identical under all three forced axis values. The digest itself
is deliberately NOT asserted as a literal - it legitimately changes whenever a
magnitude or a champion is re-authored. What is asserted is that the three forced
digests equal the baseline computed in the same run.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Iterator
from unittest import mock

from agents.daemon_slayer import antitank as at
from agents.daemon_slayer.antitank import _ANTITANK_AXES, _ANTITANK_REGISTRY

# Importable from the DS suite without hacks: the repo-root conftest.py puts the
# repo root on sys.path for BOTH suites and tests/ is a package (ADR-015).
from tests._repo_walk import EXCLUDED_DIRS, is_excluded, tracked_relpaths

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

# The cross-product R196 measured. Levels span the default (None), the two ramp
# endpoints (1 and 18) and an interior point (9) so the R17 / R39 level-ramp
# lanes are live; the stat set is non-zero on both AP and AD so every P3.2
# ap_ratio / ad_ratio seed is live too. Anything less would leave a scaling lane
# unexercised and let an axis read hide inside it.
_LEVELS = (None, 1, 9, 18)
_STAT_SETS = (None, {"ap": 300.0, "ad": 120.0})

# Kinds whose meaning is "this row lowers the target's resists" - the only rows
# on which the axis is load-bearing metadata.
_RESIST_LOWERING_KINDS = frozenset({"SHRED", "PERCENT_PEN"})

# Every callable on the antitank scoring path. None of them may so much as name
# the axis. The registry BUILDER (_build_antitank_registry) is deliberately
# excluded - it is the write side and legitimately passes axis= through.
_SCORING_FUNCTION_NAMES = (
    "_ramp_lerp_factor",
    "_level_ramp_factor",
    "_current_hp_level_ramp_factor",
    "_effective_magnitude",
    "_mechanism_value",
    "_source_sort_key",
    "_empty_result",
    "compute_antitank",
    "compute_antitank_live",
)

# This test's OWN scope skips for the structural repo scan, applied ON TOP of
# the shared tests/_repo_walk universe (ADR-015). Infrastructure exclusions
# (.git, _archive, node_modules, venvs, .claude/worktrees, responder_export)
# live in tests/_repo_walk.EXCLUDED_DIRS and are deliberately NOT repeated here.
# logs/ and data/ hold no code.
_SCAN_SKIP_DIRS = frozenset({"logs", "data"})

_DOT_AXIS_READ = re.compile(r"(?<![\w])\.axis\b")


def _in_scan_scope(rel: Path) -> bool:
    """This test's own scope: non-test ``.py`` outside ``_SCAN_SKIP_DIRS``.

    ``rel`` is RELATIVE to the walk root - matching absolute parts is the trap
    ``tests/_repo_walk.py`` documents (a checkout living under
    ``.claude/worktrees/<id>/`` would make every file look excluded).
    """
    if rel.suffix != ".py":
        return False
    if set(rel.parts) & _SCAN_SKIP_DIRS:
        return False
    if "tests" in rel.parts or rel.name.startswith("test_"):
        return False
    return True


def _iter_scan_scope(root: Path) -> Iterator[Path]:
    """Yield every in-scope ``.py`` under ``root`` per ADR-015.

    Universe = the git index first (``tracked_relpaths``; no disk walk at all),
    with ``EXCLUDED_DIRS`` as the backstop. When the index is unavailable
    (``None`` - a tmp tree, git absent, or the call failing) fall back to an
    ``os.walk`` that PRUNES ``dirnames`` in place, so the scaffolding and
    runtime-export trees are never entered. ``tests/_repo_walk.iter_repo_files``
    was scoped the same way on 2026-09-19 (index first, pruned walk on the
    fallback); this helper keeps a private copy only because it also applies
    the ``_in_scan_scope`` filter at the same point (measured 2026-09-19:
    ~96k .py under .claude/worktrees plus ~5k under ops/runtime/responder_export
    on Legion were being enumerated before either was scoped).
    """
    tracked = tracked_relpaths(str(root))
    if tracked is not None:
        for rel_posix in sorted(tracked):
            rel = Path(rel_posix)
            if is_excluded(rel) or not _in_scan_scope(rel):
                continue
            yield root / rel
        return
    prune = EXCLUDED_DIRS | _SCAN_SKIP_DIRS | {"tests"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in prune)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if _in_scan_scope(path.relative_to(root)):
                yield path


def _antitank_candidate_sources(root: Path) -> list[Path]:
    """Every in-scope ``.py`` under ``root`` whose source mentions antitank.

    Factored out with a ``root`` parameter so the pruning contract is testable
    on a tmp tree; the repo-wide pin below calls it with ``_REPO_ROOT``.
    """
    root = Path(root).resolve()
    candidates: list[Path] = []
    for path in _iter_scan_scope(root):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "antitank" not in source.lower():
            continue
        candidates.append(path)
    return candidates


def _roster() -> tuple[str, ...]:
    """Every champion in the shipped ability snapshot (171 on 16.14.1).

    Deliberately the FULL shipped roster and not ``_ANTITANK_REGISTRY`` (79
    champions): an unregistered champion's all-zero ``AntiTankResult`` is part of
    the selective-axis contract, so it belongs in the invariance population.
    """
    patch = (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()
    path = _PATCH_ROOT / patch / "champion_abilities.json"
    return tuple(sorted(json.loads(path.read_text(encoding="utf-8"))["data"]))


def _score_payload() -> list[dict]:
    """The full-precision scoring surface over the whole cross-product.

    One dict per (champion, level, stat set). Floats are carried as ``repr``
    rather than through ``to_dict`` so the 4-place rounding cannot mask a
    sub-rounding drift, and ``top_kind`` / ``shreds_resist`` are included because
    they are aggregate identities a per-mechanism probe cannot reach.
    """
    out: list[dict] = []
    for champion in _roster():
        for level in _LEVELS:
            for stats in _STAT_SETS:
                result = at.compute_antitank(
                    champion, mode="SR", stats=stats, level=level
                )
                out.append(
                    {
                        "champion": result.champion,
                        "level": level,
                        "stats": "on" if stats else "off",
                        "antitank_score": repr(result.antitank_score),
                        "top_kind": result.top_kind,
                        "shreds_resist": result.shreds_resist,
                        "sources": [
                            [
                                s.source_key,
                                s.kind,
                                s.cadence,
                                repr(s.kind_weight),
                                repr(s.cadence_mult),
                                repr(s.magnitude),
                                s.conditional,
                                repr(s.value),
                            ]
                            for s in result.sources
                        ],
                    }
                )
    return out


def _digest(payload: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("ascii")
    ).hexdigest()


@contextmanager
def _every_row_forced_to(axis: str):
    """Swap the module registry for one whose every row declares ``axis``.

    Mutates the MODULE attribute, not the imported name: ``compute_antitank``
    resolves ``_ANTITANK_REGISTRY`` as a module global, so rebinding the local
    import would be a no-op probe. Restored in a ``finally`` so the swap cannot
    leak into another test in the same process.
    """
    original = at._ANTITANK_REGISTRY
    try:
        at._ANTITANK_REGISTRY = {
            champion: tuple(replace(row, axis=axis) for row in rows)
            for champion, rows in original.items()
        }
        yield at._ANTITANK_REGISTRY
    finally:
        at._ANTITANK_REGISTRY = original


class AxisMutationProbePopulationTests(unittest.TestCase):
    """The population is the full cross-product, stated rather than sampled."""

    def test_cross_product_is_the_full_shipped_population(self) -> None:
        roster = _roster()
        self.assertEqual(len(roster), 171)
        payload = _score_payload()
        self.assertEqual(len(payload), len(roster) * len(_LEVELS) * len(_STAT_SETS))
        # The exact 1368 R196 reported, re-derived rather than restated.
        self.assertEqual(len(payload), 1368)

    def test_the_registry_is_a_strict_subset_of_the_scored_roster(self) -> None:
        # The selective axis carries 79 of the 171; the other 92 must still be
        # scored (all-zero) or the invariance population would be the easy half.
        roster = set(_roster())
        self.assertTrue(set(_ANTITANK_REGISTRY) < roster)
        self.assertEqual(len(_ANTITANK_REGISTRY), 79)


class AxisScoreInvarianceMutationProbeTests(unittest.TestCase):
    """Force every row to each axis; the whole scoring surface must not move."""

    def test_the_probe_actually_mutates_the_registry(self) -> None:
        # Anti-tautology guard. A probe whose harness silently fails to mutate
        # passes vacuously and defends nothing, so prove the swap lands and that
        # it is fully reverted afterwards.
        before = at._ANTITANK_REGISTRY
        for axis in sorted(_ANTITANK_AXES):
            with self._forced(axis) as forced:
                rows = [row for rows in forced.values() for row in rows]
                self.assertEqual(len(rows), 103)
                self.assertEqual({row.axis for row in rows}, {axis})
        self.assertIs(at._ANTITANK_REGISTRY, before)

    def test_forcing_every_row_to_each_axis_leaves_the_digest_unchanged(self) -> None:
        # The headline. The digest is compared against a baseline computed in the
        # SAME run, never a hard-coded literal - a magnitude or roster re-author
        # legitimately changes it and must not fail this module.
        baseline = _digest(_score_payload())
        for axis in sorted(_ANTITANK_AXES):
            with self.subTest(axis=axis), self._forced(axis):
                self.assertEqual(
                    _digest(_score_payload()),
                    baseline,
                    f"forcing every AntiTankEntry.axis to {axis!r} moved the"
                    " compute_antitank output - the R196 schema lift is NO"
                    " LONGER score-inert and something now reads .axis on a"
                    " scoring path",
                )

    def test_a_moved_score_names_its_champion_level_and_stat_set(self) -> None:
        # The digest above says THAT something moved; this says WHICH row, so a
        # future failure lands on a champion name instead of a hex string.
        baseline = {
            (d["champion"], d["level"], d["stats"]): d for d in _score_payload()
        }
        for axis in sorted(_ANTITANK_AXES):
            with self._forced(axis):
                for entry in _score_payload():
                    key = (entry["champion"], entry["level"], entry["stats"])
                    if entry != baseline[key]:
                        self.fail(
                            f"axis={axis!r} moved {key[0]} at level={key[1]}"
                            f" stats={key[2]}: {baseline[key]} -> {entry}"
                        )

    @contextmanager
    def _forced(self, axis: str):
        with _every_row_forced_to(axis) as registry:
            yield registry

    def tearDown(self) -> None:
        # Belt and braces: the context manager already restores, but a leaked
        # registry would silently corrupt every later antitank test in this
        # process, so re-assert the module global is the real one.
        self.assertEqual(len(at._ANTITANK_REGISTRY), 79)


class AxisReadSiteStructuralPinTests(unittest.TestCase):
    """No scoring path may READ the axis - the cheap insurance half."""

    def test_no_scoring_function_mentions_the_axis(self) -> None:
        # Reads the live function source through inspect rather than grepping the
        # file, so a scorer moved to another module is still covered. Measured
        # 2026-07-26: not one of these bodies contains the token, docstrings
        # included, so no docstring stripping is needed.
        for name in _SCORING_FUNCTION_NAMES:
            source = inspect.getsource(getattr(at, name))
            offenders = [
                line.strip()
                for line in source.splitlines()
                if re.search(r"\baxis\b", line)
            ]
            with self.subTest(function=name):
                self.assertEqual(
                    offenders,
                    [],
                    f"{name} now names the axis - the R196 metadata-only"
                    f" contract is broken at {offenders}",
                )

    def test_serializers_never_emit_the_axis(self) -> None:
        for cls in (at.AntiTankSourceEntry, at.AntiTankResult):
            source = inspect.getsource(cls.to_dict)
            with self.subTest(cls=cls.__name__):
                self.assertNotRegex(source, r"\baxis\b")

    def test_no_non_test_module_reads_dot_axis_from_an_antitank_import(self) -> None:
        # Repo-wide, dynamically discovered: any non-test .py that so much as
        # mentions antitank is a candidate holder of an AntiTankEntry, and none
        # of them may read .axis. Discovery is a walk rather than a hard-coded
        # list so a NEW consumer is covered the day it lands. Measured
        # 2026-07-26: 17 files reference antitank (16 consumers plus the module
        # itself) and every one of them has zero .axis reads. Re-measured
        # 2026-09-19 over the git-index universe (ADR-015): 16 tracked files.
        candidates = _antitank_candidate_sources(_REPO_ROOT)
        offenders: list[str] = []
        for path in candidates:
            source = path.read_text(encoding="utf-8", errors="replace")
            if _DOT_AXIS_READ.search(source):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
        self.assertGreaterEqual(
            len(candidates), 15, "the antitank consumer scan found almost nothing"
        )
        self.assertEqual(
            offenders,
            [],
            "a non-test module now reads .axis off an antitank row; if that read"
            " is on a scoring path the R196 metadata-only contract is broken:"
            f" {offenders}",
        )

    def test_antitank_candidate_scan_does_not_descend_scratch_trees(self) -> None:
        # ADR-015: a repo-root scan must PRUNE the agent-scaffolding and
        # runtime-export trees at directory level. A post-filter over rglob
        # still enumerates .claude/worktrees (~96k .py on Legion) and
        # ops/runtime/responder_export (~5k) on every DS suite run. Directory
        # arguments handed to os.scandir are the observable: os.walk and
        # Path.rglob both go through it (measured on 3.14).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            legit = root / "core" / "uses_antitank.py"
            decoys = (
                root / ".claude" / "worktrees" / "agent-x" / "core" / "z.py",
                root / "ops" / "runtime" / "responder_export" / "abcdef123456" / "core" / "z.py",
            )
            for target in (legit, *decoys):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("ROW = antitank_registry.axis\n", encoding="utf-8")
            decoy_roots = (root / ".claude", root / "ops" / "runtime" / "responder_export")

            real_scandir = os.scandir
            scanned: list[Path] = []

            def recording_scandir(path=".", *args, **kwargs):
                scanned.append(Path(os.fspath(path)).resolve())
                return real_scandir(path, *args, **kwargs)

            with mock.patch("os.scandir", recording_scandir):
                candidates = _antitank_candidate_sources(root)

            descended = sorted(
                str(d.relative_to(root))
                for d in scanned
                if any(d == base or base in d.parents for base in decoy_roots)
            )
            self.assertEqual(
                descended,
                [],
                "the antitank candidate scan descended into a scratch tree instead"
                f" of pruning it at directory level: {descended}",
            )
            # Hook-intercept anchor: an empty `descended` is only evidence if the
            # recorder saw the walk at all.
            self.assertIn(root, scanned, "os.scandir was never called on the root - the recorder saw nothing")
            self.assertEqual([p.resolve() for p in candidates], [legit])


class AxisStampedPopulationProvenanceTests(unittest.TestCase):
    """The scope of the R196 stamp, recorded so the claim keeps its subject."""

    def test_the_axis_was_stamped_on_31_rows_across_30_champions(self) -> None:
        rows = [
            (champion, row)
            for champion, rows_ in _ANTITANK_REGISTRY.items()
            for row in rows_
            if row.kind in _RESIST_LOWERING_KINDS
        ]
        self.assertEqual(len(rows), 31)
        self.assertEqual(len({champion for champion, _ in rows}), 30)

    def test_22_rows_carry_a_non_default_axis(self) -> None:
        # 22 of the 31 state PHYSICAL or MAGICAL; the other 9 state BOTH
        # explicitly. Every row of every other kind keeps the default, where the
        # field is inert by construction.
        non_default = [
            row
            for rows in _ANTITANK_REGISTRY.values()
            for row in rows
            if row.axis != "BOTH"
        ]
        self.assertEqual(len(non_default), 22)
        for row in non_default:
            self.assertIn(row.kind, _RESIST_LOWERING_KINDS)


if __name__ == "__main__":
    unittest.main()
