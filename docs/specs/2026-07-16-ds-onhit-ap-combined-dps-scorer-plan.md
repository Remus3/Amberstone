# On-hit AP Itemization (Slice B) Implementation Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Surface Nashor's Tooth (and the on-hit AP axis) for Gwen / Kayle / Kog'Maw-AP via a new combined-DPS scorer + kit-on-hit crediting + an AP/AD axis-coherence gate.

**Architecture:** v1 (compose scorer alone) was proven insufficient by live re-verify (see spec v2 section 4). The validated 3-part fix: (1) `onhit_dps.py` sums ability + on-hit-auto DPS [DONE, Tasks 1-2]; (2) credit the champs' kit on-hit magic in the auto half so AS/on-hit pays off; (3) an AP/AD axis-coherence gate so AD items (BotRK) stop burying the AP field. Then Nashor's surfaces (validated #5 for Gwen).

**Tech Stack:** Python 3.14, stdlib-only DS engine (`agents/daemon_slayer/`, mirrored to `Share/` by the `ds_share_sync` precommit hook), pytest, mkcert HTTPS dashboard.

**Spec:** `docs/specs/2026-07-16-ds-onhit-ap-combined-dps-scorer-design.md` (v2). Read it before implementing.

## Global Constraints

- ASCII ONLY: no em/en dashes, no smart quotes; ` - ` for a clause break. Precommit hook BLOCKS banned glyphs.
- `py_compile` every touched `.py` before restart.
- Atomic writes for runtime files. Never `Stop-Process`; use `taskkill /F /PID`.
- Tier-2: ENGINE_VERSION bump (`agents/daemon_slayer/__init__.py:18`, currently `"1.215.0"`, quoted-literal-only) + Share mirror + DS `:8893` restart + full dual suite + live validation.
- Do NOT modify the 6 existing scorers except the ADDITIVE, DEFAULT-OFF-for-others AA-routing extension in Task 4 (which must stay byte-identical for non-roster champs).
- New roster disjoint from `core/archetype_picks._AP_ASSASSIN_IDS`.
- Target is simulation-optimal, NOT win-rate. Acceptance = Nashor's SURFACES as a viable core AP on-hit option (not necessarily #1; Liandry's legitimately leads Gwen).
- Finish ALL DS engine edits before the full suite (a mid-suite DS bounce fabricates fails).

## Progress

- Task 1 (compute_onhit_dps): DONE, commit 5033b339, review clean.
- Task 2 (rank_items_by_onhit): DONE code-complete, commit f6d935ae. Acceptance tests present as `xfail(strict=True)` (Nashor's absent until parts 2-3 land); they FLIP to strict-pass in Task 5.

## File Structure

- `agents/daemon_slayer/onhit_dps.py` - the scorer (exists). Tasks 3+5 modify it (apply_passive_damage threading; axis-coherence).
- `agents/daemon_slayer/dps.py` - Task 4 extends `aa_routed_on_hit_entry` beyond the P-slot.
- `agents/daemon_slayer/_passive_damage_overrides.py` - Task 3 adds Gwen to `_AA_ROUTED_ON_HIT_KEYS`; Task 4 adds Kayle E + Kog'Maw W on-hit entries.
- `agents/daemon_slayer/server.py` - Task 6 adds `/rank-onhit`.
- `core/daemon_slayer_client.py` - Task 7 adds `rank_onhit_for` + the `onhit` dispatcher branch (forwards coherence + apply_passive_damage).
- `tools/ds_onhit_ap_prefilter.py` + `core/ds_onhit_ap_roster.json` - Task 9 (roster carries per-champ coherence strength).
- `core/archetype_picks.py` - Task 10 routing.
- `agents/daemon_slayer/__init__.py:18` - Task 8 ENGINE bump.

**Reference templates (READ before implementing):** `hybrid.py` (compose scorer), `_rank_mage.py` (single-scalar ranker), `dps.py:1162-1212` (AA-routed on-hit mechanism), `_passive_damage_overrides.py:599` (Gwen P entry) + `:1052-1076` (allowlist + `aa_routed_on_hit_entry`), `core/build_planner/coherence.py` (coherence patterns), `core/ds_champion_fight_length.py` (per-champ policy-map idiom for the roster).

---

## Task 3: Gwen P kit-on-hit credit + apply_passive_damage threading

**Files:**
- Modify: `agents/daemon_slayer/_passive_damage_overrides.py:1052` (allowlist)
- Modify: `agents/daemon_slayer/onhit_dps.py` (thread `apply_passive_damage`)
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Produces: `compute_onhit_dps(..., apply_passive_damage=False)` and `rank_items_by_onhit(..., apply_passive_damage=True)` - the ranker (the on-hit scorer) defaults the flag ON, `compute_onhit_dps` defaults it OFF (preserves the Task 1 exact-sum test). `compute_onhit_dps` forwards the flag to its internal `compute_dps` call.

- [ ] **Step 1: Write the failing test (Gwen P adds AS-scaling on-hit)**

```python
# append to test_onhit_dps.py
def test_gwen_p_credited_raises_auto_half_when_passive_on():
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    off = compute_onhit_dps(snap, "Gwen", 13, item_ids=("3115",), mode="SR",
                            apply_passive_damage=False, **T)
    on = compute_onhit_dps(snap, "Gwen", 13, item_ids=("3115",), mode="SR",
                           apply_passive_damage=True, **T)
    # Crediting Gwen P (now allowlisted) raises the auto half via on-hit magic.
    assert on.auto_dps > off.auto_dps
    assert on.onhit_dps > off.onhit_dps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py::test_gwen_p_credited_raises_auto_half_when_passive_on -v`
Expected: FAIL - `compute_onhit_dps` has no `apply_passive_damage` param yet (TypeError), OR (once the param exists but Gwen not allowlisted) `on.auto_dps == off.auto_dps`.

- [ ] **Step 3: Implement**

(a) In `_passive_damage_overrides.py:1052`, add Gwen to the allowlist:
```python
_AA_ROUTED_ON_HIT_KEYS: frozenset[tuple[str, str, int]] = frozenset(
    {
        ("Warwick", "P", 0),
        ("Orianna", "P", 0),
        ("Gwen", "P", 0),  # Slice B: A Thousand Cuts on-hit magic (AS-scaling)
    }
)
```
(b) In `onhit_dps.py`, add `apply_passive_damage: bool = False` to `compute_onhit_dps` and forward it to the `compute_dps(...)` call. Add `apply_passive_damage: bool = True` to `rank_items_by_onhit` and thread it into every `compute_onhit_dps` call it makes (baseline + each candidate).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: the new test PASSES; the Task 1 exact-sum test STILL passes (it uses the default `apply_passive_damage=False`); the Task 2 acceptance xfails STAY xfail (Nashor's still buried by BotRK until Task 5).

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/_passive_damage_overrides.py
git add agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/_passive_damage_overrides.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): credit Gwen P on-hit + apply_passive_damage threading (Slice B t3)"
```

---

## Task 4: Kayle E + Kog'Maw W on-hit entries + non-P AA-routing

**Files:**
- Modify: `agents/daemon_slayer/_passive_damage_overrides.py` (new entries + allowlist + `aa_routed_on_hit_entry`)
- Modify: `agents/daemon_slayer/dps.py:1183` (the routing consults the champion's AA-routed entry - already slot-agnostic via `aa_routed_on_hit_entry`, so the extension is inside that accessor)
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Consumes: `aa_routed_on_hit_entry(champion_id)` (currently P-slot-only, `_passive_damage_overrides.py:1060`).
- Produces: `aa_routed_on_hit_entry` returns Kayle's E / Kog'Maw's W on-hit rider; non-roster champs still return `None` (byte-identical).

- [ ] **Step 1: Write the failing test (Kayle + Kog on-hit credited)**

```python
# append to test_onhit_dps.py
import pytest as _pytest

@_pytest.mark.parametrize("champ", ["Kayle", "KogMaw"])
def test_kit_onhit_credited_for_kayle_kog(champ):
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    off = compute_onhit_dps(snap, champ, 13, item_ids=("3115",), mode="SR",
                            apply_passive_damage=False, **T)
    on = compute_onhit_dps(snap, champ, 13, item_ids=("3115",), mode="SR",
                           apply_passive_damage=True, **T)
    assert on.auto_dps > off.auto_dps, f"{champ}: kit on-hit not credited"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -k kit_onhit_credited -v`
Expected: FAIL - Kayle/Kog have no on-hit entry, so `on.auto_dps == off.auto_dps`.

- [ ] **Step 3: Implement**

Author Kayle E + Kog'Maw W on-hit rider entries in `_PASSIVE_DAMAGE_OVERRIDES` (verify magnitudes against `data/daemon_slayer/16.14.1/champion_abilities.json` - do NOT invent coefficients). Model each as a `PassiveDamageEntry` with `cadence="on_hit"`, keyed by their real slot (`("Kayle","E",0)`, `("KogMaw","W",0)`). Kog'Maw W is a toggle - apply an uptime discount (document the fraction). Add both keys to `_AA_ROUTED_ON_HIT_KEYS`. Extend `aa_routed_on_hit_entry` to consult the champ's routed slot (not only `"P"`) - iterate the champ's allowlisted keys instead of hardcoding `(champion_id, "P", 0)`. Keep the `entry.cadence == "on_hit"` guard. Confirm non-allowlisted champs still return `None` (byte-identical seam).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: the new Kayle/Kog tests PASS; Gwen + exact-sum tests still pass; acceptance xfails still xfail.
Also run the existing AA-routing regression to prove non-P champs unaffected:
Run: `python -m pytest agents/daemon_slayer/tests/ -k "passive_damage or aa_routed or warwick or orianna" -v` -> PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/_passive_damage_overrides.py agents/daemon_slayer/dps.py
git add agents/daemon_slayer/_passive_damage_overrides.py agents/daemon_slayer/dps.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): Kayle E + Kog'Maw W on-hit riders + non-P AA-routing (Slice B t4)"
```

---

## Task 5: AP/AD axis-coherence gate + flip acceptance tests

**Files:**
- Modify: `agents/daemon_slayer/onhit_dps.py` (`rank_items_by_onhit` axis-coherence)
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Produces: `rank_items_by_onhit(..., ap_ad_coherence: float = 0.0)` - 0.0 = off (byte-identical); higher = stronger penalty on pure-AD items (no `SpellDamage` tag) for AP-axis champs. HARD (e.g. 1.0 = effectively drop) surfaces Nashor's for Gwen; SOFT (e.g. 0.3) keeps hybrid on-hit for Kayle.

- [ ] **Step 1: Write the failing acceptance tests (flip the xfails)**

Replace the Task 2 `xfail` acceptance parametrization with a real assertion that passes the per-champ coherence strength:

```python
# in test_onhit_dps.py - replace the xfail Nashor's test
@pytest.mark.parametrize("champ,coh", [("Gwen", 1.0), ("Kayle", 0.3), ("KogMaw", 0.6)])
def test_nashors_surfaces_with_coherence(champ, coh):
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    res = rank_items_by_onhit(snap, champ, 13, current_item_ids=(), mode="SR",
                              apply_passive_damage=True, ap_ad_coherence=coh,
                              top_n=8, **T)
    ids = [r.item_id for r in res.ranked]
    assert "3115" in ids, f"{champ}: Nashor's absent from onhit top-8: {ids}"


def test_coherence_off_is_byte_identical():
    snap = DataSnapshot.load()
    T = dict(target_armor=105.0, target_mr=52.0, target_max_hp=2430.0)
    a = rank_items_by_onhit(snap, "Gwen", 13, current_item_ids=(), mode="SR",
                            apply_passive_damage=True, ap_ad_coherence=0.0, top_n=12, **T)
    # A pure-AD item (BotRK 3153) is NOT gated when coherence is off.
    assert "3153" in [r.item_id for r in a.ranked]
```

Coherence strengths are seeds - tune per-champ during Step 4 live validation (keep the value that surfaces Nashor's without mis-building the champ).

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -k "nashors_surfaces_with_coherence or coherence_off" -v`
Expected: FAIL - `ap_ad_coherence` param does not exist yet.

- [ ] **Step 3: Implement**

In `rank_items_by_onhit`, after computing each candidate's `delta_dps`, apply the coherence penalty: for an AP-axis champ (`_damage_axis(snapshot, champion_id) == "ap"`, mirror hybrid.py:73-79), a candidate whose item tags lack `"SpellDamage"` (pure-AD) has its sort score multiplied by `(1 - ap_ad_coherence)` (or dropped when `ap_ad_coherence >= 1.0`). `ap_ad_coherence == 0.0` leaves the sort byte-identical. Keep the raw `delta_dps` on the row (transparency); apply the penalty only to the sort key. Reuse the tag classification from the AP-only-pool experiment (items tagged `SpellDamage` are AP-axis).

- [ ] **Step 4: Run tests + live-tune**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: all PASS, including the (previously xfail) Nashor's-surfaces tests. If a seed coherence value does not surface Nashor's for a champ, adjust the parametrized value (the mechanism is proven; the strength is the tunable). Confirm `test_coherence_off_is_byte_identical` passes (off = no gating).

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/onhit_dps.py
git add agents/daemon_slayer/onhit_dps.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): AP/AD axis-coherence gate - Nashor's surfaces (Slice B t5)"
```

---

## Task 6: `/rank-onhit` server route

**Files:**
- Modify: `agents/daemon_slayer/server.py` (handler near `_route_rank_mage` :1081; dispatch dict :2025-2030; doc table :126-131)
- Test: `agents/daemon_slayer/tests/test_onhit_dps.py`

**Interfaces:**
- Produces: `POST /rank-onhit` -> `{"ranked": [...], ...}`. Parses the shared body PLUS `apply_passive_damage` (default True) and `ap_ad_coherence` (default 0.0), forwarding both to `rank_items_by_onhit`.

- [ ] **Step 1: Write the failing test**

```python
def test_rank_onhit_route_registered():
    from agents.daemon_slayer.server import _ROUTES  # confirm the real dispatch symbol name
    assert "/rank-onhit" in _ROUTES
```
(If the dispatch symbol differs, read server.py:2025 for the real name and match it. If server tests use an HTTP fixture, copy that idiom from an existing `test_*server*` test.)

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py::test_rank_onhit_route_registered -v`
Expected: FAIL - route not registered.

- [ ] **Step 3: Implement**

Copy `_route_rank_mage` (server.py:1081) to `_route_rank_onhit`; call `rank_items_by_onhit`; parse `apply_passive_damage` + `ap_ad_coherence` from the body (defaults True / 0.0); drop mage-only kwargs (max_priority/block_strategy). Register `"/rank-onhit": _route_rank_onhit` in the dispatch dict. Add the doc-table row (server.py:126-131).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest agents/daemon_slayer/tests/test_onhit_dps.py -v`
Expected: PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile agents/daemon_slayer/server.py
git add agents/daemon_slayer/server.py agents/daemon_slayer/tests/test_onhit_dps.py
git commit -m "feat(ds): /rank-onhit server route (Slice B t6)"
```

---

## Task 7: RC client `rank_onhit_for` + dispatcher branch

**Files:**
- Modify: `core/daemon_slayer_client.py` (`rank_mage_for` :502 template; `rank_for_primary_archetype` :1001)
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Produces: `rank_onhit_for(champion, level, ..., ap_ad_coherence=0.0, apply_passive_damage=True, ...) -> Optional[list[RankedItem]]`; `rank_for_primary_archetype(archetype="onhit", ...)` dispatches to it, resolving the per-champ coherence strength from the roster.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_onhit_ap_routing.py
from unittest.mock import patch
import core.daemon_slayer_client as dsc

def test_dispatch_routes_onhit():
    with patch.object(dsc, "rank_onhit_for", return_value=["X"]) as m:
        out = dsc.rank_for_primary_archetype("Gwen", archetype="onhit", level=13, mode="SR")
    assert m.called and out == ["X"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_dispatch_routes_onhit -v`
Expected: FAIL - `rank_onhit_for` / `onhit` branch missing.

- [ ] **Step 3: Implement**

Copy `rank_mage_for` -> `rank_onhit_for` (POST `/rank-onhit`, same fail-soft + `RankedItem` parse preserving `effective_score`/`delta_dps`), adding `ap_ad_coherence` + `apply_passive_damage` to the POST body. Add the `onhit` branch in `rank_for_primary_archetype` (kit-dependent side of the all-zero guard, :980-985); resolve the coherence strength from the roster loader (Task 9/10) - default 0.0 when unmapped.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_dispatch_routes_onhit -v`
Expected: PASS.

- [ ] **Step 5: py_compile + commit**

```bash
python -m py_compile core/daemon_slayer_client.py tests/test_onhit_ap_routing.py
git add core/daemon_slayer_client.py tests/test_onhit_ap_routing.py
git commit -m "feat(ds): rank_onhit_for client + onhit dispatcher branch (Slice B t7)"
```

---

## Task 8: Deploy gate - ENGINE bump + Share mirror + DS restart

Makes `/rank-onhit` live for Task 9's classifier validation.

- [ ] **Step 1: Bump ENGINE_VERSION**

Edit `agents/daemon_slayer/__init__.py:18`: `"1.215.0"` -> `"1.216.0"` (quoted literal only). Update any version-anchor test that pins the old literal.

- [ ] **Step 2: Full DS-dir suite ONCE**

Run: `python -m pytest agents/daemon_slayer/tests/ -q`
Expected: PASS. Trust the exit code.

- [ ] **Step 3: Commit (Share mirror same commit)**

```bash
git add agents/daemon_slayer/ Share/
git commit -m "feat(ds): ENGINE 1.216.0 - on-hit AP scorer + kit on-hit + axis coherence (Slice B t8)"
git status  # confirm Share/src/agents/daemon_slayer/onhit_dps.py + edited files mirrored + clean
```

- [ ] **Step 4: Restart DS + confirm live**

Confirm port free first, then `schtasks /End /TN RC-DaemonSlayer` + `schtasks /Run /TN RC-DaemonSlayer`. Wait to settle.
Run: `curl -sk https://127.0.0.1:8893/health` -> new engine, patch 16.14.1, alive.
Run: `curl -sk -X POST https://127.0.0.1:8893/rank-onhit -H "Content-Type: application/json" -d '{"champion":"Gwen","level":13,"mode":"SR","target_armor":105,"target_mr":52,"target_max_hp":2430,"apply_passive_damage":true,"ap_ad_coherence":1.0}'` -> Nashor's (3115) present in the ranked list.

---

## Task 9: Broad-scan classifier + roster (with coherence strength)

**Files:**
- Create: `tools/ds_onhit_ap_prefilter.py`, `core/ds_onhit_ap_roster.json`
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Produces: `core/ds_onhit_ap_roster.json` = `{"champions": {"Gwen": {"coherence": 1.0}, "Kayle": {"coherence": 0.3}, "KogMaw": {"coherence": 0.6}, ...}}`; a `load_onhit_ap_roster()` loader (in `core/archetype_picks.py` or a small `core/ds_onhit_ap_roster.py`) returning `{champ: coherence}`.

- [ ] **Step 1: Classifier tool**

Create `tools/ds_onhit_ap_prefilter.py` - iterate the champion snapshot, flag candidates that are AP-axis (`info.magic > info.attack`, fallback ability-block AP) AND attack-speed/on-hit-reliant (kit on-hit magic component OR AS steroid OR elevated `attackspeedperlevel`). Print candidates. Dev tool (no unit test).

- [ ] **Step 2: Scan + live-validate + assign coherence**

Run the tool; for each candidate probe `POST /api/ds-preview {archetype:"onhit", ...}` at varying `ap_ad_coherence` and KEEP only champs where Nashor's / an AP on-hit item genuinely surfaces AND the build reads coherent. Assign per-champ coherence (hard for AP-first, soft for hybrid). Record kept set + dropped-with-reason.

- [ ] **Step 3: Write roster + test**

Write `core/ds_onhit_ap_roster.json` (seed: Gwen hard, Kayle soft, KogMaw mid + validated additions). Test:

```python
# tests/test_onhit_ap_routing.py
import json, pathlib
def test_roster_seed_and_disjoint():
    roster = json.loads(pathlib.Path("core/ds_onhit_ap_roster.json").read_text(encoding="utf-8"))["champions"]
    assert {"Gwen", "Kayle", "KogMaw"} <= set(roster)
    from core.archetype_picks import _AP_ASSASSIN_IDS
    assert set(roster).isdisjoint(_AP_ASSASSIN_IDS)
    assert "Syndra" not in roster and "Akali" not in roster
```

- [ ] **Step 4: Run + commit**

Run: `python -m pytest tests/test_onhit_ap_routing.py::test_roster_seed_and_disjoint -v` -> PASS.
```bash
python -m py_compile tools/ds_onhit_ap_prefilter.py
git add tools/ds_onhit_ap_prefilter.py core/ds_onhit_ap_roster.json tests/test_onhit_ap_routing.py
git commit -m "feat(ds): on-hit AP classifier + validated roster w/ coherence strength (Slice B t9)"
```

---

## Task 10: RC routing in `default_for_champion`

**Files:**
- Modify: `core/archetype_picks.py` (`default_for_champion` :444; anchor at the `_AP_ASSASSIN_IDS` check :475)
- Test: `tests/test_onhit_ap_routing.py`

**Interfaces:**
- Consumes: `load_onhit_ap_roster()` (Task 9); `canonical_champion_id`.
- Produces: `default_for_champion(roster champ)` -> `("onhit", <demoted primary>)` on the default path.

- [ ] **Step 1: Failing tests**

```python
import pytest
from core.archetype_picks import default_for_champion

@pytest.mark.parametrize("champ", ["Gwen", "Kayle", "KogMaw"])
def test_routes_to_onhit(champ):
    p, s = default_for_champion(champ)
    assert p == "onhit" and s and s != "onhit"

@pytest.mark.parametrize("champ,exp", [("Syndra","mage"),("Cassiopeia","mage"),("Akali","assassin"),("Ekko","assassin")])
def test_controls_unchanged(champ, exp):
    assert default_for_champion(champ)[0] == exp
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_onhit_ap_routing.py -k "routes_to_onhit or controls_unchanged" -v`
Expected: FAIL - roster champs still resolve to `mage`.

- [ ] **Step 3: Implement**

In `default_for_champion` (:444), after `axis_correct_archetype`, alongside the `_AP_ASSASSIN_IDS` check (:475): if `canonical_champion_id(champion)` in the roster, return `("onhit", primary if primary != "onhit" else secondary)`. Cached, fail-soft loader (missing file -> empty -> byte-identical). Operator pick (early return) untouched.

- [ ] **Step 4: Run + commit + reload RC**

Run: `python -m pytest tests/test_onhit_ap_routing.py -v` -> PASS.
```bash
python -m py_compile core/archetype_picks.py
git add core/archetype_picks.py tests/test_onhit_ap_routing.py
git commit -m "feat(ds): route on-hit AP champs to the onhit scorer (Slice B t10)"
echo restart > restart_trigger.txt
```
Verify `ops/runtime/health.json`: new pid, alive, last_reload_ok.

---

## Task 11: Full dual-suite + live validation + docs

- [ ] **Step 1: Full dual suite fresh**

Run: `python -m pytest agents/daemon_slayer/tests/ -q` then `python -m pytest tests/ -q`. Report exact observed counts THIS run. Known pre-existing unrelated fails: coach-poll thread-timing x2 + ROADMAP doc-size - confirm any failure is one of those.

- [ ] **Step 2: Live-validate roster + controls**

```bash
for c in Gwen Kayle KogMaw; do curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}"; echo; done
for c in Syndra Akali; do curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}"; echo; done
```
Expected: roster champs show Nashor's; Syndra stays AP-DoT; Akali stays burst.

- [ ] **Step 3: Verifier subagent gate**

Dispatch the `verifier` subagent to independently re-run both suites, confirm cited test files exist, confirm the live probes. Green before done.

- [ ] **Step 4: Docs + LEDGER + push**

Append `docs/LEDGER.md` (max+1) for Slice B; update `docs/DAEMON_SLAYER.md` (7th scorer, ENGINE 1.216.0, no coverage-% recompute); note the overlay-render live-gated tail in `docs/LIVE_GAME_GATED_SYNC.md`; refresh `WAKEUP_NOTES.md` + `ROADMAP.md`.
```bash
git add docs/ ROADMAP.md WAKEUP_NOTES.md
git commit -m "docs(ds): sync living docs - Slice B on-hit AP itemization (LEDGER NNN)"
git push
```

- [ ] **Step 5: CI green**

Watch CI to green (a 2-3s fail = billing block; re-check locally). Declare done only on green.

---

## Self-Review

**Spec coverage:** spec 5.1 (compose scorer) -> T1-2 done. 5.2 (kit on-hit) -> T3 (Gwen) + T4 (Kayle/Kog + non-P routing). 5.3 (axis coherence) -> T5. 5.4 (routing/roster) -> T9-10. 5.5 (controls) -> T10 tests. Acceptance (Nashor's surfaces) -> T5 flip + T11 live. Release -> T8 + T11. All covered.

**Placeholder scan:** No TBD/TODO. Coefficient/magnitude authoring (T4) and coherence-strength tuning (T5/T9) are explicit "validate against source / live-tune" instructions with a proven mechanism, not placeholders.

**Type consistency:** `apply_passive_damage` (compute default False / rank default True) + `ap_ad_coherence` (float, 0.0 off) are consistent across T3/T5/T6/T7. `rank_onhit_for` / `/rank-onhit` / `archetype="onhit"` consistent T6/T7/T10. Roster shape `{champ: {"coherence": float}}` consistent T9/T7/T10.
