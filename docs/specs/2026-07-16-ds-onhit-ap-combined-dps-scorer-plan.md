# On-hit AP Combined-DPS Scorer (Slice B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 7th DS archetype scorer that sums ability DPS + on-hit-inclusive auto DPS so Nashor's Tooth surfaces for on-hit AP champions (Gwen / Kayle / Kog'Maw-AP), routed by a broad-scan classifier.

**Architecture:** A new engine module `onhit_dps.py` composes the two EXISTING damage computes (`compute_ability_dps` + `compute_dps`) into a single combined-DPS score by plain SUM (both are in the same DPS units, unlike hybrid.py's DPS+EHP mismatch). A new `/rank-onhit` server route + RC client + dispatcher branch expose it. A scan tool derives an on-hit-AP roster (validated live) that `core/archetype_picks.default_for_champion` routes to the new `onhit` archetype.

**Tech Stack:** Python 3.14, stdlib-only DS engine, mkcert HTTPS dashboard, pytest. DS engine at `agents/daemon_slayer/` (mirrored to `Share/src/agents/daemon_slayer/` by the precommit `ds_share_sync` hook on staged DS source).

## Global Constraints

- ASCII only in all authored text - no em/en dashes, no smart quotes. Use ` - ` (spaced hyphen) for a clause break. Backstopped by `tools/precommit_gate.py`.
- `py_compile` every touched `.py` before any restart (syntax errors crash silently under pythonw).
- Atomic writes only for any runtime file: `tmp.write_text(...); tmp.replace(target)`.
- Never `Stop-Process`; use `taskkill /F /PID`.
- This is Tier-2: NEW engine scorer + ENGINE_VERSION bump + Share mirror + DS `:8893` restart + full dual suite (`agents/daemon_slayer/tests/` + `tests/`) + live `/api/build-plan` validation.
- ENGINE_VERSION single source of truth: `agents/daemon_slayer/__init__.py:18` (currently `"1.215.0"`). Bump ONLY the quoted literal.
- DO NOT modify the 6 existing scorers (dps/ehp/hybrid/ability_dps/burst/hps). Additive only.
- The new roster MUST be disjoint from `core/archetype_picks._AP_ASSASSIN_IDS` (Slice A).
- Build target is simulation-optimal, NOT win-rate (memory `project_ds_build_reco_optimal_not_winrate`). Success = Nashor's surfaces + coherent build; Kayle may stay AP-leaning vs her empirical AD-hybrid meta - that is acceptable.
- Finish ALL DS-engine edits before running the full suite (memory `feedback_finish_ds_edits_before_full_suite`); a mid-suite DS bounce fabricates anchor-mismatch fails.

## File Structure

- Create `agents/daemon_slayer/onhit_dps.py` - the compose scorer: `compute_onhit_dps` + `rank_items_by_onhit` + result dataclasses. One responsibility: combined ability+auto DPS.
- Create `agents/daemon_slayer/tests/test_onhit_dps.py` - engine scorer + ranker unit tests.
- Modify `agents/daemon_slayer/server.py` - add `_route_rank_onhit` + register `/rank-onhit` + doc row.
- Modify `core/daemon_slayer_client.py` - add `rank_onhit_for` + `onhit` branch in `rank_for_primary_archetype`.
- Create `tools/ds_onhit_ap_prefilter.py` - broad-scan classifier that emits roster candidates.
- Create `core/ds_onhit_ap_roster.json` - the committed, live-validated roster (RC-side data).
- Modify `core/archetype_picks.py` - roster read + routing in `default_for_champion`.
- Modify `agents/daemon_slayer/__init__.py:18` - ENGINE_VERSION bump.
- Create `tests/test_onhit_ap_routing.py` - RC-side routing + control tests.
- Update `docs/LEDGER.md`, `ROADMAP.md`, `docs/DAEMON_SLAYER.md`, `WAKEUP_NOTES.md`, `docs/LIVE_GAME_GATED_SYNC.md`.

**Reference templates (READ before implementing):**
- `agents/daemon_slayer/hybrid.py` - the canonical compose-two-computes scorer (`compute_hybrid` at :281, `rank_items_by_hybrid` at :737). Copy its module structure; swap `compute_ehp` -> `compute_ability_dps` and the weighted-sum -> plain sum.
- `agents/daemon_slayer/_rank_mage.py` - `rank_items_by_ability_dps` is the single-scalar DPS-delta ranker (no alpha/beta). Closest template for `rank_items_by_onhit`.
- `agents/daemon_slayer/ability_dps.py` - `compute_ability_dps` (:913) returns `AbilityDpsResult` with `.total_ability_dps` + `.champion_id` + `.champion_name`.
- `agents/daemon_slayer/dps.py` - `compute_dps` returns a result with `.weighted_dps`, `.champion_id`, `.champion_name`, `.phase`, `.mode_multiplier`, `.stats`.
- `core/daemon_slayer_client.py` - `rank_mage_for` (:502) + `rank_assassin_for` (:648) are the client sibling templates; `rank_for_primary_archetype` (:1001) is the dispatcher.

---

## Task 1: Engine `compute_onhit_dps` (the compose core)

**Files:**
- Create: `agents/daemon_slayer/onhit_dps.py`
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Consumes: `compute_ability_dps(snapshot, champion_id, level, item_ids, mode, target_armor, target_mr, target_max_hp, target_bonus_hp, augments) -> AbilityDpsResult` (`.total_ability_dps`); `compute_dps(snapshot, champion_id, level, item_ids, mode, target_armor, target_mr, target_max_hp, target_bonus_hp, phase, augments, apply_mode_modifiers) -> DpsResult` (`.weighted_dps`, `.champion_id`, `.champion_name`, `.phase`, `.mode_multiplier`).
- Produces: `compute_onhit_dps(snapshot, champion_id, level, item_ids=None, mode="SR", target_armor=0.0, target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0, phase=None, augments=None, apply_mode_modifiers=False) -> OnhitDpsResult` with fields `champion_id, champion_name, level, item_ids, mode, ability_dps, auto_dps, onhit_dps, phase, target_armor, target_mr, target_max_hp, target_bonus_hp, notes` and `.to_dict()` + `.format_table()`. `onhit_dps == ability_dps + auto_dps`.

- [ ] **Step 1: Write the failing test (exact-sum invariant + both halves present)**

```python
# agents/daemon_slayer/tests/test_onhit_dps.py
from agents.daemon_slayer.data_loader import load_default_snapshot
from agents.daemon_slayer.onhit_dps import compute_onhit_dps
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.dps import compute_dps

# Nashor's Tooth + Rabadon's - an on-hit AP build for Gwen.
_GWEN_BUILD = ("3115", "3089")


def test_onhit_dps_is_exact_sum_of_two_halves():
    snap = load_default_snapshot()
    res = compute_onhit_dps(
        snap, "Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    )
    ability = compute_ability_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).total_ability_dps
    auto = compute_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).weighted_dps
    assert res.ability_dps == ability
    assert res.auto_dps == auto
    assert res.onhit_dps == ability + auto
    # Both halves are material for an on-hit AP champ (the whole point).
    assert res.ability_dps > 0.0
    assert res.auto_dps > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py::test_onhit_dps_is_exact_sum_of_two_halves -v`
Expected: FAIL - `ModuleNotFoundError: agents.daemon_slayer.onhit_dps` (or `load_default_snapshot` import - if that helper name differs, read `data_loader.py` for the real snapshot loader used by `hybrid.py`'s tests and match it).

- [ ] **Step 3: Write minimal implementation**

Read `hybrid.py:1-60` + `:179-280` (imports + `HybridResult`) for the scaffold, then create `onhit_dps.py`. The compute is a plain sum:

```python
"""Slice B (2026-07-16) - on-hit AP combined-DPS scorer.

Composes compute_ability_dps().total_ability_dps (Q/W/E/R) with
compute_dps().weighted_dps (autos + on-hit item procs, incl. Nashor's
Icathian Bite) into ONE combined-DPS score by PLAIN SUM - both halves are
in the same DPS units. The two are non-overlapping by design: the passive
(P) on-hit lives in compute_dps, the four active spells live in
compute_ability_dps. Neither half alone surfaces Nashor's; their sum is the
champion's true total sustained DPS. Sibling of hybrid.py (which composes
dps + EHP with alpha/beta) - here no weights are needed.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .ability_dps import compute_ability_dps
from .data_loader import DataSnapshot
from .dps import compute_dps
from .stats import clamp_level


@dataclass(frozen=True)
class OnhitDpsResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    ability_dps: float          # compute_ability_dps().total_ability_dps
    auto_dps: float             # compute_dps().weighted_dps (incl. on-hit procs)
    onhit_dps: float            # ability_dps + auto_dps (plain sum, same units)
    phase: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "ability_dps": self.ability_dps,
            "auto_dps": self.auto_dps,
            "onhit_dps": self.onhit_dps,
            "phase": self.phase,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ON-HIT AP]"
        )
        rows = [head, "-" * len(head)]
        rows.append(f"items: {', '.join(self.item_ids) if self.item_ids else '(none)'}")
        rows.append(
            f"  ability_dps  {self.ability_dps:.2f}\n"
            f"  auto_dps     {self.auto_dps:.2f}\n"
            f"  onhit_dps    {self.onhit_dps:.2f}  (sum)"
        )
        for n in self.notes:
            rows.append(f"  note: {n}")
        return "\n".join(rows)


def compute_onhit_dps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    phase: Optional[str] = None,
    augments: Optional[Iterable] = None,
    apply_mode_modifiers: bool = False,
) -> OnhitDpsResult:
    """Combined ability + on-hit-auto DPS for the resolved build (plain sum)."""
    level = clamp_level(level)
    item_list = tuple(str(i) for i in (item_ids or ()))

    auto = compute_dps(
        snapshot, champion_id=champion_id, level=level, item_ids=item_list,
        mode=mode, target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        phase=phase, augments=augments, apply_mode_modifiers=apply_mode_modifiers,
    )
    ability = compute_ability_dps(
        snapshot, champion_id=champion_id, level=level, item_ids=item_list,
        mode=mode, target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        augments=augments,
    )
    ability_dps = float(ability.total_ability_dps)
    auto_dps = float(auto.weighted_dps)
    return OnhitDpsResult(
        champion_id=auto.champion_id,
        champion_name=auto.champion_name,
        level=level,
        item_ids=item_list,
        mode=mode,
        ability_dps=ability_dps,
        auto_dps=auto_dps,
        onhit_dps=ability_dps + auto_dps,
        phase=auto.phase,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        notes=(f"onhit_dps = ability {ability_dps:.1f} + auto {auto_dps:.1f}",),
    )
```

Note: if `compute_dps` does NOT accept `target_bonus_hp` or `apply_mode_modifiers` with these exact names, read its signature in `dps.py` and match (hybrid.py:397-411 shows the real call). Do NOT invent kwargs.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py::test_onhit_dps_is_exact_sum_of_two_halves -v`
Expected: PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/tests/test_onhit_dps.py
git add agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): compute_onhit_dps - combined ability + on-hit-auto DPS (Slice B t1)"
```

---

## Task 2: Engine `rank_items_by_onhit` (the ranker)

**Files:**
- Modify: `agents/daemon_slayer/onhit_dps.py`
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Consumes: `compute_onhit_dps` (Task 1); `rank._filter_candidates`, `rank._is_terminal`, `rank.strip_arena_trinkets`, `rank._champion_is_melee`, `rank.DEFAULT_SLOT_COUNT`, `rank.DEFAULT_TOP_N`, `rank.SORT_KEYS`; `effects.ITEM_EFFECTS`.
- Produces: `rank_items_by_onhit(snapshot, champion_id, level, current_item_ids=None, mode="SR", target_armor=0.0, target_mr=0.0, target_max_hp=0.0, target_bonus_hp=0.0, phase=None, budget=None, slot_count=DEFAULT_SLOT_COUNT, top_n=DEFAULT_TOP_N, include_components=False, only_item_ids=None, sort_by="delta", augments=None, apply_mode_modifiers=False, filter_shared_uniques=True) -> OnhitDpsRankResult` whose `.ranked` is a tuple of `OnhitDpsRankedItem(item_id, item_name, gold, delta_dps, new_dps, ability_dps, auto_dps, is_terminal, tags, unique_passive_key, shares_dead_unique, dead_unique_key, dps_per_1k_gold)`. Sort key `delta` = `delta_dps` desc; `efficiency` = `dps_per_1k_gold` desc.

- [ ] **Step 1: Write the failing test (Nashor's surfaces for all three champs)**

```python
# append to agents/daemon_slayer/tests/test_onhit_dps.py
import pytest
from agents.daemon_slayer.onhit_dps import rank_items_by_onhit

_NASHORS = "3115"


@pytest.mark.parametrize("champ", ["Gwen", "Kayle", "KogMaw"])
def test_nashors_surfaces_in_onhit_topn(champ):
    snap = load_default_snapshot()
    res = rank_items_by_onhit(
        snap, champ, level=13, current_item_ids=(), mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0, top_n=8,
    )
    ids = [r.item_id for r in res.ranked]
    assert _NASHORS in ids, f"{champ}: Nashor's absent from onhit top-8: {ids}"


def test_onhit_ranked_row_splits_are_consistent():
    snap = load_default_snapshot()
    res = rank_items_by_onhit(
        snap, "Gwen", level=13, current_item_ids=(), mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0, top_n=8,
    )
    r = res.ranked[0]
    # new_dps == ability_dps + auto_dps for each row (the sum invariant holds per candidate).
    assert abs(r.new_dps - (r.ability_dps + r.auto_dps)) < 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -k nashors -v`
Expected: FAIL - `rank_items_by_onhit` not defined.

- [ ] **Step 3: Write minimal implementation**

Read `_rank_mage.py` `rank_items_by_ability_dps` in full - it is the single-scalar delta ranker. Mirror its structure exactly (candidate filter loop, dead-unique dedup, sort, top_n, notes) but score each candidate with `compute_onhit_dps(build).onhit_dps`. Key deltas from the mage ranker:
- baseline = `compute_onhit_dps(snapshot, champ, level, current_ids, ...).onhit_dps`.
- per candidate `new_build = current_ids + (item_id,)`; `scored = compute_onhit_dps(..., new_build, ...)`; `delta_dps = scored.onhit_dps - baseline`; carry `ability_dps=scored.ability_dps`, `auto_dps=scored.auto_dps`, `new_dps=scored.onhit_dps`.
- `dps_per_1k_gold = (delta_dps / (gold/1000.0)) if (gold>0 and delta_dps>0) else 0.0`.
- reuse `_filter_candidates(..., champion_is_melee=_champion_is_melee(champ_rec, augments))`, `strip_arena_trinkets`, `_is_terminal`, the `ITEM_EFFECTS` dead-unique dedup, and `SORT_KEYS` validation exactly as hybrid.py:846-1148.
- `OnhitDpsRankedItem` + `OnhitDpsRankResult` dataclasses mirror `HybridRankedItem`/`HybridRankResult` (hybrid.py:535-660) minus every EHP/alpha/beta field, plus `ability_dps` + `auto_dps` splits.

Wrap each per-candidate compute in `try: ... except (KeyError, ValueError): continue` (hybrid.py:1062).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: PASS (all - the exact-sum, the 3 Nashor's params, the row-split).
If Nashor's does NOT surface for a champ, DO NOT weaken the assertion - this is the acceptance signal. Diagnose: confirm the champ is AP-axis and that `compute_dps` credits their kit on-hit; if a champ genuinely does not want Nashor's under simulation, drop it from the parametrize list AND record why (it will also be dropped from the Task 6 roster).

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/onhit_dps.py
git add agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): rank_items_by_onhit - Nashor's surfaces for on-hit AP champs (Slice B t2)"
```

---

## Task 3: Server `/rank-onhit` route

**Files:**
- Modify: `agents/daemon_slayer/server.py` (handler near the other `_route_rank_*` at :777/:1081/:1708; dispatch dict at :2025-2030; doc table at :126-131)
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Consumes: `rank_items_by_onhit` (Task 2); the existing shared body parser used by `_route_rank_mage` (`server.py:1081`).
- Produces: `POST /rank-onhit` returning `{"ranked": [row.to_dict()...], ...}` mirroring the `/rank-mage` response envelope.

- [ ] **Step 1: Write the failing test (in-process route dispatch)**

```python
# append to test_onhit_dps.py - mirror how test_* exercises other routes
from agents.daemon_slayer.server import _DISPATCH  # or the real dispatch symbol

def test_rank_onhit_route_registered():
    assert "/rank-onhit" in _DISPATCH
```

If server tests are driven by an HTTP client fixture rather than `_DISPATCH`, read an existing `test_*server*.py` (e.g. `tests/test_ds_preview_*`) and copy its route-exercise pattern instead. Match the repo's actual server-test idiom.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py::test_rank_onhit_route_registered -v`
Expected: FAIL - `/rank-onhit` not in dispatch.

- [ ] **Step 3: Write minimal implementation**

Copy `_route_rank_mage` (server.py:1081) to a new `_route_rank_onhit`, swapping the compute call to `rank_items_by_onhit` and dropping mage-only kwargs (max_priority/block_strategy are ability-scorer knobs; keep whatever the shared parser already supplies, drop what `rank_items_by_onhit` does not accept). Register `"/rank-onhit": _route_rank_onhit` in the dispatch dict (server.py:2025-2030). Add the doc-table row near server.py:126-131:

```python
# in the HTML doc table block
"<tr><td>POST</td><td>/rank-onhit</td><td>rank items by combined ability+on-hit-auto DPS delta (Slice B)</td></tr>"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/server.py
git add agents/daemon_slayer/server.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): /rank-onhit server route (Slice B t3)"
```

---

## Task 4: RC client `rank_onhit_for` + dispatcher branch

**Files:**
- Modify: `core/daemon_slayer_client.py` (`rank_mage_for` at :502 is the template; `rank_for_primary_archetype` at :1001 is the dispatcher)
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Consumes: `_post_json("/rank-onhit", body, timeout)`; the `RankedItem` parse used by `rank_for` / `rank_mage_for` (preserve `effective_score` + `delta_dps`, memory `reference_ds_client_effective_score_parse`).
- Produces: `rank_onhit_for(champion, level, ...) -> Optional[list[RankedItem]]`; `rank_for_primary_archetype(..., archetype="onhit", ...)` dispatches to it.

- [ ] **Step 1: Write the failing test (dispatcher routes onhit)**

```python
# tests/test_onhit_ap_routing.py
from unittest.mock import patch
import core.daemon_slayer_client as dsc


def test_rank_for_primary_archetype_routes_onhit():
    with patch.object(dsc, "rank_onhit_for", return_value=["SENTINEL"]) as m:
        out = dsc.rank_for_primary_archetype("Gwen", archetype="onhit", level=13, mode="SR")
    assert m.called
    assert out == ["SENTINEL"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_rank_for_primary_archetype_routes_onhit -v`
Expected: FAIL - `rank_onhit_for` attribute missing / `onhit` branch absent (may raise on unknown archetype).

- [ ] **Step 3: Write minimal implementation**

Copy `rank_mage_for` (daemon_slayer_client.py:502) to `rank_onhit_for`, POSTing `/rank-onhit`, same fail-soft (None on engine failure) + same `RankedItem` parse. In `rank_for_primary_archetype` (:1001), add a branch alongside the ds.ability/ds.burst branches:

```python
    if archetype == "onhit":
        return rank_onhit_for(
            champion, level=level, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            top_n=top_n, timeout=timeout,
            # forward the same kit-dependent / hp_pct inputs the mage branch uses
        )
```

Keep `onhit` on the KIT-DEPENDENT side of the all-zero-kit guard (daemon_slayer_client.py:980-985) so a kit-less champ does not 0.0-collapse. Match the exact kwargs the sibling mage branch forwards.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_rank_for_primary_archetype_routes_onhit -v`
Expected: PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile core/daemon_slayer_client.py tests/test_onhit_ap_routing.py
git add core/daemon_slayer_client.py tests/test_onhit_ap_routing.py
git commit -m "feat(ds): rank_onhit_for client + onhit dispatcher branch (Slice B t4)"
```

---

## Task 5: Deploy gate - ENGINE bump + Share mirror + DS restart

This task makes `/rank-onhit` LIVE so Task 6 can validate the classifier against it. No new test file - the deliverable is a live, green engine.

**Files:**
- Modify: `agents/daemon_slayer/__init__.py:18` (ENGINE_VERSION)

- [ ] **Step 1: Bump ENGINE_VERSION (quoted literal only)**

Edit `agents/daemon_slayer/__init__.py:18`: `ENGINE_VERSION = "1.215.0"` -> `ENGINE_VERSION = "1.216.0"`. Change ONLY the quoted literal (memory `feedback_engine_bump_quoted_literal_only`).

- [ ] **Step 2: Confirm all engine edits are done, then run the DS-dir suite ONCE**

Run: `python -m pytest agents/daemon_slayer/tests/ -q`
Expected: PASS (full green). Trust the exit code (R6). If a version-anchor test pins `1.215.0`, update it to `1.216.0` (that is an intended bump, not a regression).

- [ ] **Step 3: Commit (stage Share mirror in the SAME commit)**

The precommit `ds_share_sync` hook mirrors staged `agents/daemon_slayer/` source into `Share/src/agents/daemon_slayer/`. Stage the engine tree so the hook fires:

```bash
git add agents/daemon_slayer/ Share/
git commit -m "feat(ds): ENGINE 1.216.0 - on-hit AP combined-DPS scorer wired (Slice B t5)"
git status  # confirm Share/src/agents/daemon_slayer/onhit_dps.py is now tracked + clean
```

Verify `onhit_dps.py` + `server.py` + the test file mirrored into `Share/src/...` (memory `feedback_ds_commit_share_test_mirror` + `feedback_share_mirror_tools_drift`). If the mirror did not fire, re-run the sync per `docs/OPERATIONS.md`.

- [ ] **Step 4: Restart DS `:8893` + confirm live**

Confirm the port is free first (detached child gotcha, memory `reference_ds_server_not_supervisor_watched`), then:

```bash
schtasks /End /TN RC-DaemonSlayer
schtasks /Run /TN RC-DaemonSlayer
```

Wait for the Share sync + restart to settle, then:

Run: `curl -sk https://127.0.0.1:8893/health` -> expect `patch=16.14.1` and the new engine alive. Then smoke the route:
Run: `curl -sk -X POST https://127.0.0.1:8893/rank-onhit -H "Content-Type: application/json" -d '{"champion":"Gwen","level":13,"mode":"SR","target_armor":105,"target_mr":52,"target_max_hp":2430}'` -> expect a ranked list containing item 3115.

---

## Task 6: Broad-scan classifier + validated roster

**Files:**
- Create: `tools/ds_onhit_ap_prefilter.py`
- Create: `core/ds_onhit_ap_roster.json`
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Consumes: the champion snapshot (`agents/daemon_slayer/data_loader`); `hybrid._damage_axis` logic (info.magic > info.attack); live `/rank-onhit` (from Task 5).
- Produces: `core/ds_onhit_ap_roster.json` = `{"champions": ["Gwen", "Kayle", "KogMaw", ...], "generated": "...", "predicate": "..."}` (canonical DDragon ids). A `load_onhit_ap_roster() -> frozenset[str]` helper (put it in `core/archetype_picks.py` in Task 7, or a small `core/ds_onhit_ap_roster.py` loader - pick one and be consistent).

- [ ] **Step 1: Write the classifier + emit candidates**

Create `tools/ds_onhit_ap_prefilter.py` that iterates the champion snapshot and flags candidates where BOTH hold: (a) AP damage axis (`info.magic > info.attack`, fallback `_classify_primary_scaling == "AP"`); (b) attack-speed / on-hit reliance (a kit on-hit MAGIC component that scales AP, OR an AS-steroid ability, OR elevated `stats.attackspeedperlevel`). Print the candidate list. This is a dev tool (no unit test required for the tool itself; it is validated by its output).

- [ ] **Step 2: Run the scan + LIVE-validate each candidate**

Run the tool to list candidates. For EACH candidate, probe the live route and compare to the current default:

```bash
python tools/ds_onhit_ap_prefilter.py   # -> candidate list
# for each candidate:
curl -sk -X POST https://127.0.0.1:8888/api/ds-preview -H "Content-Type: application/json" \
  -d '{"champion":"<C>","mode":"SR","level":13,"archetype":"onhit"}'
```

KEEP a candidate in the roster only when an on-hit-AP item (Nashor's / Guinsoo / on-hit family) genuinely surfaces AND the build reads coherent (per-champion validation, CLAUDE.md "Engine / Build Conventions"). Record the kept set + the reason any candidate was dropped.

- [ ] **Step 3: Write the validated roster + its membership test**

Write `core/ds_onhit_ap_roster.json` with the validated champion ids (seed: `Gwen`, `Kayle`, `KogMaw`, plus any validated additions). Then the test:

```python
# append to tests/test_onhit_ap_routing.py
import json, pathlib

def test_roster_contains_seed_and_is_disjoint_from_ap_assassins():
    roster = set(json.loads(
        pathlib.Path("core/ds_onhit_ap_roster.json").read_text(encoding="utf-8")
    )["champions"])
    assert {"Gwen", "Kayle", "KogMaw"} <= roster
    from core.archetype_picks import _AP_ASSASSIN_IDS
    assert roster.isdisjoint(_AP_ASSASSIN_IDS)
    # controls must NOT be routed
    assert "Syndra" not in roster and "Cassiopeia" not in roster
    assert "Akali" not in roster and "Ekko" not in roster
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_roster_contains_seed_and_is_disjoint_from_ap_assassins -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
python -m py_compile tools/ds_onhit_ap_prefilter.py
git add tools/ds_onhit_ap_prefilter.py core/ds_onhit_ap_roster.json tests/test_onhit_ap_routing.py
git commit -m "feat(ds): on-hit AP broad-scan classifier + validated roster (Slice B t6)"
```

---

## Task 7: RC routing in `default_for_champion` + RC reload

**Files:**
- Modify: `core/archetype_picks.py` (`default_for_champion` at :444; the `_AP_ASSASSIN_IDS` check at :475 is the insertion anchor)
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Consumes: `core/ds_onhit_ap_roster.json` (Task 6); `canonical_champion_id`.
- Produces: `default_for_champion(champion)` returns `("onhit", <demoted primary>)` for a roster champ on the default path.

- [ ] **Step 1: Write the failing tests (routing + controls + operator-pick-wins)**

```python
# append to tests/test_onhit_ap_routing.py
import pytest
from core.archetype_picks import default_for_champion


@pytest.mark.parametrize("champ", ["Gwen", "Kayle", "KogMaw"])
def test_onhit_ap_champs_route_to_onhit(champ):
    primary, secondary = default_for_champion(champ)
    assert primary == "onhit"
    assert secondary and secondary != "onhit"


@pytest.mark.parametrize("champ,expected", [
    ("Syndra", "mage"), ("Cassiopeia", "mage"),   # pure mages unchanged
    ("Akali", "assassin"), ("Ekko", "assassin"),  # Slice A AP assassins unchanged
])
def test_controls_unchanged(champ, expected):
    primary, _ = default_for_champion(champ)
    assert primary == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_onhit_ap_routing.py -k "route_to_onhit or controls_unchanged" -v`
Expected: FAIL - roster champs still resolve to `mage` (Gwen/Kayle) today.

- [ ] **Step 3: Write minimal implementation**

In `default_for_champion` (archetype_picks.py:444), add a roster loader (module-level, cached) and a routing check immediately alongside the `_AP_ASSASSIN_IDS` block at :475:

```python
    cid = canonical_champion_id(champion)
    if cid in _load_onhit_ap_roster():
        # on-hit AP: route the default to the combined-DPS scorer; demote the
        # tag-derived primary to secondary so the operator can flip back.
        return ("onhit", primary if primary != "onhit" else secondary)
```

Place it so an explicit operator pick (which returns early higher in the function) is untouched, and after `axis_correct_archetype` so `primary`/`secondary` are resolved. `_load_onhit_ap_roster` reads `core/ds_onhit_ap_roster.json` once, cached, fail-soft to an empty set (a missing file -> no routing, byte-identical).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_onhit_ap_routing.py -v`
Expected: PASS (all).

- [ ] **Step 5: py_compile, commit, reload RC**

```bash
python -m py_compile core/archetype_picks.py
git add core/archetype_picks.py tests/test_onhit_ap_routing.py
git commit -m "feat(ds): route on-hit AP champs to the onhit scorer (Slice B t7)"
echo restart > restart_trigger.txt
```

Verify: read `ops/runtime/health.json` - confirm new `pid`, `alive=true`, `last_reload_ok=true`.

---

## Task 8: Full dual-suite green + live validation + docs

**Files:**
- Update: `docs/LEDGER.md`, `ROADMAP.md`, `docs/DAEMON_SLAYER.md`, `WAKEUP_NOTES.md`, `docs/LIVE_GAME_GATED_SYNC.md`

- [ ] **Step 1: Run the full dual suite fresh (Verification Discipline - re-verify green)**

```bash
python -m pytest agents/daemon_slayer/tests/ -q
python -m pytest tests/ -q
```
Expected: PASS. Report the exact observed pass/fail counts from THIS run (never carry a prior count forward). Pre-existing unrelated fails known this session: coach-poll thread-timing x2 + ROADMAP doc-size - confirm any failure is one of these, not new.

- [ ] **Step 2: Live-validate roster + controls via `/api/build-plan`**

```bash
for c in Gwen Kayle KogMaw; do
  curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" \
    -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}"; echo; done
for c in Syndra Akali; do   # controls
  curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" \
    -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}"; echo; done
```
Expected: roster champs show Nashor's in the build; Syndra stays AP-DoT; Akali stays burst.

- [ ] **Step 2b: Verifier subagent gate**

Dispatch the `verifier` subagent to independently re-run both suites from clean, confirm every cited test file exists, and confirm the live probes. Do not declare done until it returns green (CLAUDE.md Verification Discipline).

- [ ] **Step 3: Docs sync + LEDGER (append-only, newest-first)**

Append a `docs/LEDGER.md` entry (max-existing +1) describing Slice B. Update `docs/DAEMON_SLAYER.md` (7th scorer, ENGINE 1.216.0) - do NOT recompute coverage % in a general sync (memory `feedback_ds_coverage_prose_recompute`). Note the live-gated overlay RENDER eyeball in `docs/LIVE_GAME_GATED_SYNC.md`. Refresh `WAKEUP_NOTES.md` + `ROADMAP.md` (Slice B done; next Slice if any).

- [ ] **Step 4: Commit docs + push**

```bash
git add docs/LEDGER.md docs/DAEMON_SLAYER.md ROADMAP.md WAKEUP_NOTES.md docs/LIVE_GAME_GATED_SYNC.md
git commit -m "docs(ds): sync living docs - Slice B on-hit AP combined-DPS scorer (LEDGER NNN)"
git push
```

- [ ] **Step 5: Confirm CI green**

Watch the push CI to green (memory `reference_ci_billing_fastfail` - a 2-3s fail is a billing block, re-check locally). Declare done only on green.

---

## Self-Review

**Spec coverage:** Section 5.1 (scorer module) -> Tasks 1-2. 5.2 (route+client+dispatcher) -> Tasks 3-4. 5.3 (classifier+roster) -> Task 6. 5.4 (RC routing) -> Task 7. 5.5 (self-limiting) -> validated by Task 6 controls + Task 7 control tests. 5.6 (controls) -> Task 7 tests. 5.7 (double-count audit) -> Task 1 exact-sum test + Task 2 row-split test. 5.8 (data flow) -> Tasks 4/7. Section 6 (tests) -> distributed. Section 7 (release) -> Tasks 5/8. All spec sections covered.

**Placeholder scan:** No TBD/TODO. Where an exact signature could not be verified from this session's reads (compute_dps kwargs, the server test idiom, the mage-ranker body), the step names the exact template file:line to copy from and warns against inventing kwargs - this is a deliberate "read the template" instruction, not a placeholder.

**Type consistency:** `onhit_dps` (the scalar) is used consistently in Task 1 (result field), Task 2 (ranker score + `new_dps`), Task 5 (route smoke). `OnhitDpsResult.ability_dps/auto_dps/onhit_dps` names match across Tasks 1/2. `rank_onhit_for` / `/rank-onhit` / `archetype="onhit"` consistent across Tasks 3/4/7. Roster file `core/ds_onhit_ap_roster.json` consistent across Tasks 6/7.
