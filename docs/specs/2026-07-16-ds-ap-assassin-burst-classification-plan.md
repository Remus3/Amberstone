# AP-Assassin Burst Classification (Slice A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the 7 curated AP burst-assassins to the AP-capable `ds.burst` scorer instead of the sustained `ds.ability` (Liandry's-DoT) scorer, via a default-archetype override.

**Architecture:** Add a curated `_AP_ASSASSIN_IDS` frozenset to `core/archetype_picks.py` and short-circuit `default_for_champion` to return `("assassin", "mage")` for its members. This only affects the DDragon-tag DEFAULT (an operator pick still wins via the early return in `get_archetype_for`). The DS engine (`agents/daemon_slayer/`) is byte-unchanged - the `ds.burst` scorer already flows AP amplification; we only fix which champions reach it.

**Tech Stack:** Python 3.14, pytest. Pure `core/` change + test updates. No new deps.

## Global Constraints

- **ASCII only.** No em-dashes / en-dashes / smart quotes anywhere (repo hard rule). Use ` - ` for a clause break. `tools/precommit_gate.py` blocks banned glyphs + net-new ruff on staged lines.
- **Python interpreter:** `C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe` (referred to as `python` below). Run all commands from repo root `C:/Riot Commander`.
- **`py_compile` any edited `.py` before an RC restart** (syntax errors crash silently under `pythonw.exe`).
- **RC reload = write any content to `restart_trigger.txt`** (supervisor clears + restarts within ~5s). Then confirm `ops/runtime/health.json` shows a new `pid`, `alive=true`, `last_reload_ok=true`.
- **NO ENGINE_VERSION bump. NO Share mirror stage. NO DS `:8893` restart.** The engine is unchanged (C4 caller-default-flip precedent: RC-side change + RC reload only).
- **Commit to `main`** (RC solo-dev convention). Commit messages: plain ASCII, conventional-commit style.
- **Override set is exactly 7 canonical DDragon ids:** `Akali, Ekko, Evelynn, Fizz, Katarina, Leblanc, Diana`. Note `Leblanc` (lowercase b) is the canonical id. Kassadin/Sylas/Vex are deliberately EXCLUDED (rationale in Task 1 Step 3 comment).

---

### Task 1: Add the AP-assassin override + repoint the stale axis-correction test

**Files:**
- Modify: `core/archetype_picks.py` (add constant near line 145; add branch in `default_for_champion` ~line 456, before the final `return`)
- Create: `tests/test_ap_assassin_override.py`
- Modify: `tests/test_archetype_axis_correction.py` (remove 7 keys from `EXPECTED_FLIPS`; fix its comment)

**Interfaces:**
- Consumes: `core.archetype_picks.canonical_champion_id(name) -> str` (exists, line 382); `default_for_champion(champion) -> tuple[str, str]` (exists, line 429); `get_archetype_for(champion) -> dict` (exists, line 592).
- Produces: `core.archetype_picks._AP_ASSASSIN_IDS: frozenset[str]`. `default_for_champion` returns `("assassin", "mage")` for any champion whose canonical id is in that set.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ap_assassin_override.py`:

```python
"""Slice A (2026-07-16 AP-axis sweep) - AP burst-assassin classification.

DDragon tags + the P6 axis correction collapse AP-kit assassins to `mage`
(the sustained ds.ability scorer, Liandry's-DoT), because axis_correct_archetype
tags the assassin archetype as AD-only. But ds.burst flows AP amplification
(burst.py: a Diana / Akali build registers their AP amp), so these short-window
burst assassins belong on it. This pins the curated override that routes them to
`assassin`, plus the controls that must NOT move.
"""
from __future__ import annotations

import pytest

from core import archetype_picks as ap


@pytest.fixture(autouse=True)
def _fresh_caches():
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()
    yield
    ap._invalidate_axis_cache()
    ap._invalidate_picks_cache()


AP_ASSASSINS = ["Akali", "Ekko", "Evelynn", "Fizz", "Katarina", "LeBlanc", "Diana"]


@pytest.mark.parametrize("champ", AP_ASSASSINS)
def test_ap_assassin_defaults_to_assassin(champ, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    primary, secondary = ap.default_for_champion(champ)
    assert primary == "assassin", f"{champ} should route to the burst scorer"
    assert secondary == "mage"


@pytest.mark.parametrize("champ", AP_ASSASSINS)
def test_ap_assassin_get_archetype_for_primary(champ, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    info = ap.get_archetype_for(champ)
    assert info["primary"] == "assassin"
    assert info["source"] == "default"


# Controls: the override must NOT pull these onto the burst scorer.
@pytest.mark.parametrize("champ,expected", [
    ("Qiyana", "assassin"),    # AD assassin - already burst, unchanged
    ("Zed", "assassin"),       # AD assassin - unchanged
    ("Syndra", "mage"),        # ranged sustained mage - stays mage
    ("Cassiopeia", "mage"),    # DoT mage - stays mage
    ("Pyke", "assassin"),      # AD kit via enchanter->assassin correction - unchanged
    ("Gwen", "mage"),          # on-hit AP (Slice B owns it) - unchanged
    ("Kayle", "mage"),         # on-hit AP - unchanged
    ("Kassadin", "mage"),      # EXCLUDED: scaling mana-assassin, default already Rabadon's-led
])
def test_controls_unchanged(champ, expected, monkeypatch):
    monkeypatch.setattr(ap, "_load_picks", lambda: {})
    assert ap.default_for_champion(champ)[0] == expected


def test_operator_pick_still_wins(monkeypatch):
    # An explicit mage pick on Akali must not be overridden by the AP-assassin set.
    monkeypatch.setattr(ap, "_load_picks", lambda: {
        "Akali": {"champion": "Akali", "primary": "mage",
                  "secondary": "assassin", "source": ap.SOURCE_USER_CS},
    })
    info = ap.get_archetype_for("Akali")
    assert info["primary"] == "mage"
    assert info["source"] == ap.SOURCE_USER_CS
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `python -m pytest tests/test_ap_assassin_override.py -q`
Expected: FAIL - `test_ap_assassin_defaults_to_assassin` gets `mage` (currently every seed champ resolves to `('mage', ...)`). Controls + operator-pick tests should already pass.

- [ ] **Step 3: Add the override constant**

In `core/archetype_picks.py`, after `_AXIS_MARGIN_MIN = 0.20` (line ~144), add:

```python
# AP burst-assassin override (2026-07-16 AP-axis sweep, Slice A). DDragon tags +
# axis_correct_archetype collapse these AP-kit assassins to `mage` (assassin is
# tagged AD-axis, and _AP_AXIS_ARCHETYPE == "mage"), landing them on the sustained
# ds.ability scorer (Liandry's-DoT). They are short-window burst assassins; the
# ds.burst scorer already flows the full AP amp pipeline (see burst.py), so route
# them there. Canonical DDragon ids. Only the tag DEFAULT is touched - an operator
# pick (source != default) still wins via get_archetype_for's early return.
# EXCLUDED and why: Kassadin (scaling mana-assassin - his default already leads
# Rabadon's not Liandry's, and neither scorer models his mana core); Sylas (AP
# bruiser - wants sustained Riftmaker, not burst); Vex (ranged control mage).
_AP_ASSASSIN_IDS: frozenset[str] = frozenset({
    "Akali", "Ekko", "Evelynn", "Fizz", "Katarina", "Leblanc", "Diana",
})
```

- [ ] **Step 4: Add the override branch in `default_for_champion`**

In `core/archetype_picks.py`, in `default_for_champion`, replace the final block:

```python
    corrected = axis_correct_archetype(champion, primary, tags)
    if corrected != primary:
        secondary = primary
        primary = corrected
    return (primary, secondary)
```

with:

```python
    corrected = axis_correct_archetype(champion, primary, tags)
    if corrected != primary:
        secondary = primary
        primary = corrected
    # Slice A: curated AP burst-assassins are collapsed to mage by the tag path +
    # axis correction; force them onto the assassin (ds.burst) scorer. Surface the
    # would-be mage archetype as the alt-view so the operator can flip back.
    if canonical_champion_id(champion) in _AP_ASSASSIN_IDS:
        return ("assassin", "mage")
    return (primary, secondary)
```

- [ ] **Step 5: py_compile + run the new test to verify it passes**

Run: `python -m py_compile core/archetype_picks.py && python -m pytest tests/test_ap_assassin_override.py -q`
Expected: PASS (all parametrized cases green).

- [ ] **Step 6: Run the axis-correction test to confirm the expected breakage**

Run: `python -m pytest tests/test_archetype_axis_correction.py -q`
Expected: FAIL on `test_default_archetype_rebased_to_kit_axis` for `Akali, Diana, Ekko, Evelynn, Fizz, Katarina, Leblanc` (they now resolve to `assassin`, but `EXPECTED_FLIPS` says `mage`). This is expected - fix it next.

- [ ] **Step 7: Repoint `EXPECTED_FLIPS` in the axis-correction test**

In `tests/test_archetype_axis_correction.py`, the comment above `EXPECTED_FLIPS` currently reads (line ~35): `# 11 named by the lolmath-vs-DS sweep + 7 AP assassins the manual sweep missed # (assassin scorer is AD/lethality) + Pyke ...`. Replace the whole `EXPECTED_FLIPS` block with (removes the 7 override champs; the "assassin scorer is AD/lethality" premise was disproven - ds.burst handles AP):

```python
# Champions whose tag default was on the WRONG damage axis and must re-base to
# `mage`. The AP burst-assassins (Akali/Ekko/Evelynn/Fizz/Katarina/Leblanc/Diana)
# used to appear here as "mage" too, but they are now routed to the ds.burst
# scorer by the curated _AP_ASSASSIN_IDS override (the ds.burst scorer flows AP
# amp - it is NOT AD-only). Their classification is covered by
# tests/test_ap_assassin_override.py. Kassadin stays mage (excluded from the
# override); Pyke is an AD kit corrected off the AP enchanter scorer.
EXPECTED_FLIPS = {
    "Gwen": "mage", "Teemo": "mage", "Rumble": "mage",
    "Mordekaiser": "mage", "KogMaw": "mage", "Nidalee": "mage", "Elise": "mage",
    "Gragas": "mage", "Lillia": "mage", "Kassadin": "mage",
    "Pyke": "assassin",
}
```

- [ ] **Step 8: Run both archetype tests to verify green**

Run: `python -m pytest tests/test_ap_assassin_override.py tests/test_archetype_axis_correction.py -q`
Expected: PASS (both files fully green).

- [ ] **Step 9: Commit**

```bash
git -C "C:/Riot Commander" add core/archetype_picks.py tests/test_ap_assassin_override.py tests/test_archetype_axis_correction.py
git -C "C:/Riot Commander" commit -m "feat(ds): route AP burst-assassins to the ds.burst scorer (Slice A, AP-axis sweep)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Full-suite verification, live validation, reload, LEDGER

**Files:**
- Modify: `docs/LEDGER.md` (append newest-first)
- Modify (only if a probe reveals it): any other test asserting a seed champ = mage

**Interfaces:**
- Consumes: the Task 1 override (live after RC reload).
- Produces: nothing new - this task ships + records.

- [ ] **Step 1: Sweep the broader archetype test set for other stale expectations**

Run: `python -m pytest tests/test_archetype_dispatcher.py tests/test_archetype_dispatch_seam.py tests/test_build_order_axis_parity.py tests/test_build_plan_contract.py tests/test_coach_archetype_dispatch.py -q`
Expected: PASS. If any FAILS because it asserts one of the 7 champs resolves to `mage`/`ability`, update that single expectation to the new value (`assassin`/`burst`) with a one-line comment referencing `_AP_ASSASSIN_IDS`, then re-run that file. Do NOT weaken an unrelated assertion.

- [ ] **Step 2: Run the full RC test suite once**

Run: `python -m pytest tests/ -q`
Expected: PASS (0 failed). Trust the exit code (efficiency rule R6). If a failure cites a seed champ's archetype, apply the same targeted repoint as Step 1; re-run only the affected file, then this line once more.

- [ ] **Step 3: Reload RC so the running dashboard picks up the change**

```bash
echo restart > "C:/Riot Commander/restart_trigger.txt"
```

Wait ~6s, then:
Run: `python -c "import json;d=json.load(open(r'C:/Riot Commander/ops/runtime/health.json'));print(d['pid'],d['alive'],d.get('last_reload_ok'))"`
Expected: a new `pid`, `True`, `True`.

- [ ] **Step 4: Live-validate the 7 flip to a burst AP build**

```bash
cd "C:/Riot Commander" && for c in Akali Ekko Evelynn Fizz Katarina LeBlanc Diana; do
curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}" | python -c "import sys,json;d=json.load(sys.stdin);b=[i.get('item_name') for i in d.get('live',[])];print('$c',d.get('plan_meta',{}).get('scorer'),'|',' > '.join(b))"
done
```
Expected: every champ shows `scorer == burst` and an AP-led build (Rabadon's / Void Staff / Lich Bane / Shadowflame leading), NOT `Liandry's Torment` first.

- [ ] **Step 5: Live-validate the controls did not move**

```bash
cd "C:/Riot Commander" && for c in Qiyana Syndra Gwen Kassadin; do
curl -sk -X POST https://127.0.0.1:8888/api/build-plan -H "Content-Type: application/json" -d "{\"champion\":\"$c\",\"mode\":\"SR\",\"level\":13}" | python -c "import sys,json;d=json.load(sys.stdin);print('$c',d.get('plan_meta',{}).get('scorer'))"
done
```
Expected: `Qiyana burst` (AD assassin, unchanged), `Syndra ability`, `Gwen ability`, `Kassadin ability`.

- [ ] **Step 6: Append the LEDGER entry (newest-first)**

Prepend a dated entry to `docs/LEDGER.md` describing: the AP-axis sweep Slice A - 7 AP burst-assassins (Akali/Ekko/Evelynn/Fizz/Katarina/Leblanc/Diana) rerouted from the sustained ds.ability scorer to ds.burst via `_AP_ASSASSIN_IDS` in `core/archetype_picks.py`; root cause = axis_correct_archetype collapsing AP assassins to mage on the wrong "burst scorer is AD-only" premise; RC-side only (no ENGINE bump / no Share / no DS restart); the disproven premise fixed in `test_archetype_axis_correction.py`; Slice B (on-hit AP / Nashor's) still owed. Reference the spec + this plan by path.

- [ ] **Step 7: Commit the LEDGER + any Step-1/2 test fixes**

```bash
git -C "C:/Riot Commander" add docs/LEDGER.md tests/
git -C "C:/Riot Commander" commit -m "docs(ds): LEDGER - AP-assassin burst reroute Slice A + test repoints" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
git -C "C:/Riot Commander" push
```

---

## Self-Review

**1. Spec coverage:**
- Root cause (spec section 3) -> Task 1 Steps 3-4 fix `default_for_champion`. Covered.
- Curated override mechanism (spec 4, 5.1) -> Task 1 Step 3 `_AP_ASSASSIN_IDS`. Covered.
- Champion set + exclusions (spec 5.2) -> Task 1 Step 3 constant + comment; Evelynn included (validated live), Kassadin/Sylas/Vex excluded. Covered.
- Controls (spec 5.3) -> Task 1 Step 1 `test_controls_unchanged` + Task 2 Step 5. Covered.
- Tests RED-first (spec 5.6) -> Task 1 Steps 1-2, 6. Covered.
- Release: no ENGINE/Share/DS-restart, full suite, live validation, reload (spec 5.7) -> Global Constraints + Task 2. Covered.
- Deferred: AD-artifact filter, per-champ combos, Slice B (spec 5.4, 7) -> explicitly NOT in this plan. Correct.

**2. Placeholder scan:** No TBD/TODO. Step 1 of Task 2 is a conditional repoint with an exact pattern (not a vague "handle failures"). All code blocks are complete.

**3. Type consistency:** `_AP_ASSASSIN_IDS` (frozenset[str]) defined in Task 1 Step 3, consumed in Step 4 via `canonical_champion_id(champion) in _AP_ASSASSIN_IDS`. `default_for_champion` returns `tuple[str, str]` consistently. Test helper names match the module's real API (`_invalidate_axis_cache`, `_invalidate_picks_cache`, `_load_picks`, `save`/`get_archetype_for`, `SOURCE_USER_CS`) - all verified against `core/archetype_picks.py`.

## Notes for the implementer

- The `ds.burst` builds carry mid-pack AD artifacts (BORK / Lord Dominik's). That is a KNOWN, deferred follow-up (spec 5.4) - do NOT try to filter them in this plan; the reroute is a net win without it.
- If live probes are unavailable (RC down / no `:8888`), Task 2 Steps 4-5 are gated on the reload succeeding in Step 3; do not skip - fix the reload first.
