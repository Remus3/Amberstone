# Boot Utility Scorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a comp-conditioned per-boot utility scorer, gated behind a DEFAULT-OFF `assume_boot_utility` seam, so a build's boots are chosen on their full utility profile vs the enemy comp instead of a coarse single-axis heuristic.

**Architecture:** New pure engine primitive `agents/daemon_slayer/boot_utility.py` (Share-mirrored, ENGINE-versioned) scores each tier-2 boot on a normalized utility vector weighted by the comp. `core/build_order._select_boots` gains an OFF-default flag: OFF returns today's heuristic verbatim (byte-identical committed tables), ON returns the utility argmax with archetype-default hysteresis. `plan_build_order` threads the flag; the comp signal (`enemy_ad_share`/`enemy_ap_share`) is read from the existing `rank_kwargs`.

**Tech Stack:** Python 3.14 (`C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`), pytest, the DS engine package `agents/daemon_slayer`, the Share mirror (`ds_share_sync`).

## Global Constraints

- ASCII only. No em-dashes / en-dashes / smart quotes in any authored file (CLAUDE.md hard rule; `tools/precommit_gate.py` blocks banned glyphs).
- `py_compile` every touched `.py` before any DS restart.
- Tier-2 change: ENGINE_VERSION bump + full dual suite (`agents/daemon_slayer/tests` + `tests/`) + Share mirror `--check` clean + DS `:8893` restart.
- ENGINE bump = replace ONLY the quoted literal. Current: `ENGINE_VERSION = "1.185.0"` at `agents/daemon_slayer/__init__.py:18` -> `"1.186.0"`.
- Byte-identical OFF contract: with `assume_boot_utility=False` (every caller today), `_select_boots` returns EXACTLY the current heuristic result. Do NOT refactor the OFF branch - add the ON branch before it and leave the existing lines verbatim.
- New required params appended at END with defaults (Python-conventions rule: never insert mid-signature).
- Share-mirror atomicity: `agents/daemon_slayer/boot_utility.py` + `__init__.py` are DS-mirrored sources. Stage the canonical file + its Share mirror in the SAME commit (the precommit gate auto-runs `ds_share_sync`; verify with `--check`). `core/build_order.py` + `tests/` are NOT mirrored.
- Never `Stop-Process`; restart DS via `taskkill /F /PID <pid>` then relaunch `start_daemon_slayer.py` (`:8893` is NOT supervisor-watched).

## File Structure

- Create `agents/daemon_slayer/boot_utility.py` - the pure scorer: `BOOT_UTILITY_PROFILE`, `comp_weights`, `score_boot`, `select_boot`, `SELECTABLE_TIER2`. One responsibility: score/rank boots. No I/O, no engine imports.
- Create `agents/daemon_slayer/tests/test_boot_utility.py` - unit tests for the primitive.
- Modify `core/build_order.py` - `_select_boots` gains the OFF-default flag + comp params + a `_select_boots_utility` helper; the single caller (line 526) threads them; `plan_build_order` gains `assume_boot_utility`.
- Create `tests/test_boot_utility_select.py` - consumer tests (OFF parity + ON re-rank through `_select_boots` and `plan_build_order`).
- Modify `agents/daemon_slayer/__init__.py:18` - ENGINE_VERSION bump.
- Modify `agents/daemon_slayer/CHANGELOG.md` - one entry.
- Create `ops/audit/boot_utility_preview_diff.py` - non-committing preview-diff reporter (prints only; writes no table).

---

### Task 1: Boot utility scoring primitive

**Files:**
- Create: `agents/daemon_slayer/boot_utility.py`
- Test: `agents/daemon_slayer/tests/test_boot_utility.py`

**Interfaces:**
- Produces:
  - `BOOT_UTILITY_PROFILE: dict[str, dict[str, float]]`
  - `SELECTABLE_TIER2: tuple[str, ...]`
  - `comp_weights(archetype: str, enemy_ad_share: float, enemy_ap_share: float, cc_proxy: float) -> dict[str, float]`
  - `score_boot(boot_id: str, weights: dict[str, float]) -> float`
  - `select_boot(pool: Iterable[str], weights: dict[str, float], default_id: str, switch_margin: float = _SWITCH_MARGIN) -> str`

- [ ] **Step 1: Write the failing tests**

Create `agents/daemon_slayer/tests/test_boot_utility.py`:

```python
"""Unit tests for the DEFAULT-OFF boot utility scorer (agents/daemon_slayer/boot_utility.py)."""
from __future__ import annotations

from agents.daemon_slayer import boot_utility as bu

NEUTRAL = dict(enemy_ad_share=0.5, enemy_ap_share=0.5, cc_proxy=0.0)


def _w(archetype, **over):
    ctx = {**NEUTRAL, **over}
    return bu.comp_weights(archetype, ctx["enemy_ad_share"], ctx["enemy_ap_share"], ctx["cc_proxy"])


def test_profile_covers_selectable_pool():
    for bid in bu.SELECTABLE_TIER2:
        assert bid in bu.BOOT_UTILITY_PROFILE, bid


def test_marksman_neutral_comp_keeps_berserkers():
    # DPS kit, no defensive signal -> archetype default (Berserker's 3006) holds.
    assert bu.select_boot(bu.SELECTABLE_TIER2, _w("marksman"), "3006") == "3006"


def test_marksman_high_ap_cc_flips_to_mercurys():
    w = _w("marksman", enemy_ad_share=0.2, enemy_ap_share=0.8, cc_proxy=0.9)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3006") == "3111"


def test_high_ad_flips_to_steelcaps():
    w = _w("mage", enemy_ad_share=0.9, enemy_ap_share=0.1, cc_proxy=0.0)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3020") == "3047"


def test_hysteresis_marginal_signal_holds_default():
    # A weak AD lean must NOT dislodge the archetype default (below switch margin).
    w = _w("marksman", enemy_ad_share=0.55, enemy_ap_share=0.45, cc_proxy=0.0)
    assert bu.select_boot(bu.SELECTABLE_TIER2, w, "3006") == "3006"


def test_failsoft_unknown_boot_scores_zero_and_empty_pool_returns_default():
    assert bu.score_boot("999999", _w("carry")) == 0.0
    assert bu.select_boot((), _w("carry"), "3006") == "3006"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest agents/daemon_slayer/tests/test_boot_utility.py -q`
Expected: FAIL / ERROR - `ModuleNotFoundError: No module named 'agents.daemon_slayer.boot_utility'`.

- [ ] **Step 3: Write the module**

Create `agents/daemon_slayer/boot_utility.py`:

```python
"""Comp-conditioned per-boot utility scorer (DEFAULT-OFF assume_boot_utility seam).

Pure + self-contained: no engine imports, no I/O. Consumed by
core.build_order._select_boots only on the ON path; OFF stays byte-identical.

Each tier-2 boot carries a NORMALIZED utility vector over axes; the comp
supplies per-axis weights; the boot's score is the dot product. A challenger
must beat the champion's archetype-default boot by a relative margin to win
(hysteresis, mirrors core.build_order._pick_top_safe incumbent_margin). All
weights + the margin are conservative operator-tunable starters, in the spirit
of hybrid.py _MS_UTILITY_DPS_FRACTION.

Boot ids are 16.13.1 DDragon tier-2 forms (Arena 22-prefix mirror is applied
by the caller AFTER selection). Symbiotic Soles 3010 is rune-granted (not
shop-buyable) so it is scored but NOT in SELECTABLE_TIER2.
"""
from __future__ import annotations

from typing import Iterable

# Tier-2 boot ids.
BERSERKERS = "3006"   # attack speed
SWIFTNESS = "3009"    # move speed + slow-resist
SYMBIOTIC = "3010"    # move speed (rune-granted; scored, not selectable)
SORCERERS = "3020"    # magic pen
STEELCAPS = "3047"    # armor + R80 AA-damage-reduction
MERCURYS = "3111"     # magic resist + 30% tenacity
IONIAN = "3158"       # ability haste + summoner haste

# Directly-purchasable tier-2 boots the ON path may select (excludes the
# rune-only Symbiotic 3010 so the scorer never recommends an unbuyable boot).
SELECTABLE_TIER2: tuple[str, ...] = (
    BERSERKERS, SWIFTNESS, SORCERERS, STEELCAPS, MERCURYS, IONIAN,
)

# Per-boot normalized utility vector, seeded from the 16.13.1 stat profile
# (cross-checked vs _item_tenacity.py, _item_ability_haste.py, and the R80
# AA-damage-reduction registry). CONSERVATIVE STARTER - operator-tunable.
BOOT_UTILITY_PROFILE: dict[str, dict[str, float]] = {
    BERSERKERS: {"as_dps": 1.0},
    SWIFTNESS:  {"move_speed": 1.0},
    SYMBIOTIC:  {"move_speed": 0.7},
    SORCERERS:  {"magic_pen": 1.0},
    STEELCAPS:  {"armor_survival": 1.0},
    MERCURYS:   {"mr_survival": 0.8, "tenacity": 1.0},
    IONIAN:     {"ability_haste": 1.0},
}

# Archetype -> the champ-kit axis it intrinsically wants (the prior). Mirrors
# core.build_order._DEFAULT_BOOTS_BY_ARCHETYPE expressed as an axis.
_ARCHETYPE_AXIS: dict[str, str] = {
    "carry": "as_dps", "marksman": "as_dps", "adc": "as_dps", "dps": "as_dps",
    "mage": "magic_pen", "burst": "magic_pen",
    "assassin": "ability_haste", "enchanter": "ability_haste",
    "hps": "ability_haste", "ability": "ability_haste", "support": "ability_haste",
    "tank": "armor_survival", "ehp": "armor_survival", "bruiser": "armor_survival",
}

# Tunable weights. The kit-axis prior is the incumbent the comp must overcome.
_KIT_AXIS_WEIGHT = 1.0     # weight on the champ's own kit axis (the prior)
_DEFENSE_WEIGHT = 1.0      # how hard enemy AD/AP share pulls to armor/MR boots
_TENACITY_WEIGHT = 0.8     # weight on tenacity, scaled by the CC proxy
_MOVE_SPEED_WEIGHT = 0.35  # small standing value for MS (kite/roam)
# A challenger must beat the archetype default by this RELATIVE margin to win.
_SWITCH_MARGIN = 0.15


def comp_weights(
    archetype: str,
    enemy_ad_share: float,
    enemy_ap_share: float,
    cc_proxy: float,
) -> dict[str, float]:
    """Per-axis weights for a comp. cc_proxy in [0,1] is the caller's CC estimate."""
    kit_axis = _ARCHETYPE_AXIS.get((archetype or "carry").strip().lower(), "as_dps")
    weights: dict[str, float] = {}
    weights[kit_axis] = weights.get(kit_axis, 0.0) + _KIT_AXIS_WEIGHT
    weights["armor_survival"] = weights.get("armor_survival", 0.0) + _DEFENSE_WEIGHT * float(enemy_ad_share)
    weights["mr_survival"] = weights.get("mr_survival", 0.0) + _DEFENSE_WEIGHT * float(enemy_ap_share)
    weights["tenacity"] = weights.get("tenacity", 0.0) + _TENACITY_WEIGHT * float(cc_proxy)
    weights["move_speed"] = weights.get("move_speed", 0.0) + _MOVE_SPEED_WEIGHT
    return weights


def score_boot(boot_id: str, weights: dict[str, float]) -> float:
    """Dot product of the boot's utility vector with the comp weights. 0.0 if unknown."""
    profile = BOOT_UTILITY_PROFILE.get(str(boot_id), {})
    return sum(profile.get(axis, 0.0) * w for axis, w in weights.items())


def select_boot(
    pool: Iterable[str],
    weights: dict[str, float],
    default_id: str,
    switch_margin: float = _SWITCH_MARGIN,
) -> str:
    """Argmax boot over pool, but the challenger must beat default by switch_margin.

    Fail-soft: an empty pool returns default_id.
    """
    ids = [str(b) for b in pool]
    if not ids:
        return default_id
    default_score = score_boot(default_id, weights)
    challenger = max(ids, key=lambda b: score_boot(b, weights))
    if challenger != str(default_id) and score_boot(challenger, weights) > default_score * (1.0 + switch_margin):
        return challenger
    return str(default_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest agents/daemon_slayer/tests/test_boot_utility.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: py_compile**

Run: `python -m py_compile agents/daemon_slayer/boot_utility.py agents/daemon_slayer/tests/test_boot_utility.py`
Expected: no output (success).

(Commit is deferred to Task 5's Tier-2 finalize so the Share mirror lands in the same commit.)

---

### Task 2: Wire the seam into `_select_boots`

**Files:**
- Modify: `core/build_order.py` (`_select_boots` at 228-273; single caller at 526-531)
- Test: `tests/test_boot_utility_select.py`

**Interfaces:**
- Consumes: `agents.daemon_slayer.boot_utility.{comp_weights, select_boot, SELECTABLE_TIER2}` (Task 1)
- Produces: `_select_boots(archetype, target_armor, target_mr, mode="SR", enemy_ad_share=0.5, enemy_ap_share=0.5, assume_boot_utility=False) -> tuple[str, str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_boot_utility_select.py`:

```python
"""Consumer tests: core.build_order._select_boots OFF parity + ON re-rank."""
from __future__ import annotations

from core.build_order import _select_boots


def test_off_is_byte_identical_marksman_lockdown():
    # OFF: DPS-axis champ is hard-pinned to Berserker's regardless of comp.
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="SR",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=False)
    assert iid == "3006"


def test_off_parity_grid_unchanged():
    # Pin the current heuristic outputs (OFF path) for a representative grid.
    cases = [
        (("marksman", 0.0, 0.0, "SR"), "3006"),
        (("mage", 0.0, 0.0, "SR"), "3020"),
        (("tank", 0.0, 0.0, "SR"), "3047"),
        (("assassin", 0.0, 0.0, "SR"), "3158"),
        (("carry", 0.0, 70.0, "SR"), "3111"),   # target_mr>=60, not dps-axis? carry IS dps-axis -> stays 3006
        (("bruiser", 0.0, 70.0, "SR"), "3111"),  # target_mr>=60, not dps-axis -> Mercury's
        (("mage", 120.0, 0.0, "SR"), "3020"),    # target_armor>=100 but caster-axis -> keeps Sorcerer's
        (("tank", 120.0, 0.0, "SR"), "3047"),    # target_armor>=100, not caster -> Steelcaps
    ]
    for (arch, armor, mr, mode), expected in cases:
        iid, _ = _select_boots(arch, armor, mr, mode=mode, assume_boot_utility=False)
        assert iid == expected, (arch, armor, mr, iid)


def test_on_marksman_lockdown_flips_to_mercurys():
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="SR",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=True)
    assert iid == "3111"


def test_on_arena_mirror_applied():
    iid, _ = _select_boots("marksman", 0.0, 70.0, mode="CHERRY",
                           enemy_ad_share=0.2, enemy_ap_share=0.8,
                           assume_boot_utility=True)
    assert iid == "223111"
```

Note: verify the `carry` + `target_mr>=60` expectation against the live OFF branch first (`is_dps_axis` includes `carry`, so it stays `3006`); adjust the pinned value only if the current code disagrees - the point is OFF == today.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_boot_utility_select.py -q`
Expected: FAIL - `_select_boots() got an unexpected keyword argument 'enemy_ad_share'`.

- [ ] **Step 3: Edit `_select_boots` (add ON branch + params; leave OFF verbatim)**

In `core/build_order.py`, replace the `_select_boots` signature line and body-head. New signature (append the 3 params at END):

```python
def _select_boots(
    archetype: str,
    target_armor: float,
    target_mr: float,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    assume_boot_utility: bool = False,
) -> tuple[str, str]:
```

Replace the selection block (current lines 258-266) with an ON-branch-first version; the OFF branch is the existing lines verbatim:

```python
    arch = (archetype or "carry").strip().lower() or "carry"
    if assume_boot_utility:
        iid = _select_boots_utility(
            arch, float(target_armor), float(target_mr),
            float(enemy_ad_share), float(enemy_ap_share),
        )
    else:
        is_dps_axis = arch in ("dps", "carry", "marksman", "adc")
        is_caster_axis = arch in ("mage", "burst", "enchanter", "hps", "ability", "support")
        if target_mr >= 60.0 and not is_dps_axis:
            iid = "3111"
        elif target_armor >= 100.0 and not is_caster_axis:
            iid = "3047"
        else:
            iid = _DEFAULT_BOOTS_BY_ARCHETYPE.get(arch, "3006")
    mode_up = str(mode).strip().upper()
    if mode_up in _ARENA_MODES:
        iid = _BOOTS_ARENA_MIRROR.get(iid, iid)
    return (iid, _BOOTS_NAMES.get(iid, "Boots"))
```

Add the helper immediately above `_select_boots`:

```python
def _select_boots_utility(
    arch: str,
    target_armor: float,
    target_mr: float,
    enemy_ad_share: float,
    enemy_ap_share: float,
) -> str:
    """ON-path boot pick: comp-conditioned utility argmax with archetype-default
    hysteresis. Lazy-imports the DS primitive (byte-identical OFF never touches it)."""
    from agents.daemon_slayer import boot_utility as bu
    default_id = _DEFAULT_BOOTS_BY_ARCHETYPE.get(arch, "3006")
    # v1 CC proxy: enemy AP share plus a bump when the enemy is MR-relevant
    # (frontline/AP comps carry more lockdown). Real per-champion CC is a follow-up.
    cc_proxy = min(1.0, float(enemy_ap_share) + (0.3 if target_mr >= 60.0 else 0.0))
    weights = bu.comp_weights(arch, float(enemy_ad_share), float(enemy_ap_share), cc_proxy)
    return bu.select_boot(bu.SELECTABLE_TIER2, weights, default_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_boot_utility_select.py -q`
Expected: PASS. If `test_off_parity_grid_unchanged` fails on a pinned value, the pin was wrong (not the code) - correct the expected value to match the untouched OFF heuristic and re-run.

- [ ] **Step 5: py_compile**

Run: `python -m py_compile core/build_order.py`
Expected: no output.

---

### Task 3: Thread the flag through `plan_build_order`

**Files:**
- Modify: `core/build_order.py` (`plan_build_order` signature 418-438; caller 526-531)
- Test: `tests/test_boot_utility_select.py` (add cases)

**Interfaces:**
- Consumes: `_select_boots(..., enemy_ad_share, enemy_ap_share, assume_boot_utility)` (Task 2)
- Produces: `plan_build_order(..., assume_boot_utility: bool = False)`; the caller reads `enemy_ad_share`/`enemy_ap_share` from `extra` (rank_kwargs).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_boot_utility_select.py`:

```python
from core.build_order import plan_build_order


def _stub_rank_fn(**kwargs):
    # Minimal ranker: one damage item so plan_build_order has a slot to fill;
    # boots are injected separately by _select_boots.
    return {"rows": [{"item_id": "3031", "item_name": "Infinity Edge",
                      "delta": 100.0, "gold": 3450, "unit": "dps",
                      "dead_unique_key": "", "unique_passive_key": ""}]}


def _boot_of(res):
    return next((s.item_id for s in res.order if s.item_id in {
        "3006", "3009", "3020", "3047", "3111", "3158"}), None)


def test_plan_build_order_off_keeps_default_boot():
    res = plan_build_order(
        "Kalista", "marksman", level=11, owned_item_ids=[], mode="SR",
        target_mr=70.0, rank_kwargs={"enemy_ad_share": 0.2, "enemy_ap_share": 0.8},
        rank_fn=_stub_rank_fn, assume_boot_utility=False,
    )
    assert _boot_of(res) == "3006"


def test_plan_build_order_on_flips_boot_for_comp():
    res = plan_build_order(
        "Kalista", "marksman", level=11, owned_item_ids=[], mode="SR",
        target_mr=70.0, rank_kwargs={"enemy_ad_share": 0.2, "enemy_ap_share": 0.8},
        rank_fn=_stub_rank_fn, assume_boot_utility=True,
    )
    assert _boot_of(res) == "3111"
```

Verify the stub's `rows` shape against the real `rank_fn` contract before running (grep `dispatch_for_coach` / `_pick_top_safe` for the exact row keys); adjust keys if the engine expects more.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_boot_utility_select.py -k plan_build_order -q`
Expected: FAIL - `plan_build_order() got an unexpected keyword argument 'assume_boot_utility'`.

- [ ] **Step 3: Edit `plan_build_order`**

Append to the keyword-only params (after `incumbent_margin: float = 0.03,`):

```python
    assume_boot_utility: bool = False,
```

Replace the `_select_boots` call (current 526-531) with:

```python
        boots_id, boots_name = _select_boots(
            arch,
            float(target_armor),
            float(target_mr),
            mode=str(mode),
            enemy_ad_share=float(extra.get("enemy_ad_share", 0.5)),
            enemy_ap_share=float(extra.get("enemy_ap_share", 0.5)),
            assume_boot_utility=assume_boot_utility,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_boot_utility_select.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: py_compile**

Run: `python -m py_compile core/build_order.py`
Expected: no output.

---

### Task 4: ENGINE bump + CHANGELOG

**Files:**
- Modify: `agents/daemon_slayer/__init__.py:18`
- Modify: `agents/daemon_slayer/CHANGELOG.md`

- [ ] **Step 1: Bump the quoted literal**

Edit `agents/daemon_slayer/__init__.py:18`: `ENGINE_VERSION = "1.185.0"` -> `ENGINE_VERSION = "1.186.0"`. Change ONLY that literal.

- [ ] **Step 2: Add a CHANGELOG entry**

Prepend under the newest-first header in `agents/daemon_slayer/CHANGELOG.md`:

```markdown
## 1.186.0 (2026-07-09) - boot utility scorer (DEFAULT-OFF assume_boot_utility)

New agents/daemon_slayer/boot_utility.py: comp-conditioned per-boot utility
scorer. Consumed by core/build_order._select_boots behind the DEFAULT-OFF
assume_boot_utility seam. OFF path byte-identical (committed tables unchanged);
ON path selects the best tier-2 boot on its full utility profile vs the comp
(AD/AP share + a v1 CC proxy) with archetype-default hysteresis. Capability
added, committed output unchanged - same shape as R58 assume_ms_utility.
```

- [ ] **Step 3: py_compile**

Run: `python -m py_compile agents/daemon_slayer/__init__.py`
Expected: no output.

---

### Task 5: Tier-2 finalize - dual suite + Share sync + commit + DS restart

**Files:** (stage together) all created/modified `.py`, the ENGINE bump, CHANGELOG, and the auto-synced Share mirror.

- [ ] **Step 1: Full dual suite**

Run: `python -m pytest agents/daemon_slayer/tests tests -q`
Expected: PASS (existing count + the new tests; no regressions). Write the result to a file if the pipe is noisy: append `> ops/runtime/_boot_suite.txt 2>&1` and read it back (Verification Discipline).

- [ ] **Step 2: Verify Share mirror will sync (dry check)**

Run: `python tools/ds_share_sync.py --check` (path per repo; the precommit gate also runs it). If it reports drift, that is EXPECTED pre-commit (the new boot_utility.py is not yet mirrored) - the commit's gate will sync it. Re-run `--check` AFTER commit to confirm clean.

- [ ] **Step 3: Commit (canonical + Share mirror in ONE commit)**

```bash
cd "C:/Riot Commander"
git add agents/daemon_slayer/boot_utility.py agents/daemon_slayer/tests/test_boot_utility.py \
        core/build_order.py tests/test_boot_utility_select.py \
        agents/daemon_slayer/__init__.py agents/daemon_slayer/CHANGELOG.md \
        Share/
git commit -F - <<'EOF'
feat(ds): comp-aware boot utility scorer, DEFAULT-OFF (ENGINE 1.185.0 -> 1.186.0)

New agents/daemon_slayer/boot_utility.py scores each tier-2 boot on its full
utility profile (as/pen/haste/armor/mr/tenacity/ms) weighted by the enemy comp;
core/build_order._select_boots picks the argmax with archetype-default
hysteresis behind the DEFAULT-OFF assume_boot_utility seam. OFF byte-identical
(committed tables unchanged); plan_build_order threads the flag + reads
enemy_ad_share/enemy_ap_share from rank_kwargs. BACKLOG "Daemon Slayer scorer
calibration" enhancement #2. Flip default-ON is a follow-up (live-game gated).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: Confirm Share `--check` clean post-commit**

Run: `python tools/ds_share_sync.py --check`
Expected: in sync (no drift).

- [ ] **Step 5: Restart DS :8893 and verify**

Get the pid: `python -c "import json;print(json.load(open(r'ops/runtime/health.json')).get('pid'))"` is RC, not DS - instead find the DS pid via the RC-DaemonSlayer task / `netstat -ano | findstr :8893`. Then:

```
taskkill /F /PID <ds_pid>
python agents/daemon_slayer/start_daemon_slayer.py   (or the documented launcher; pythonw for no console)
```

Verify: `curl -k http://127.0.0.1:8893/health` -> `engine_version` == `1.186.0`, `patch` == `16.13.1`, `alive` true. Wait for the Share sync + DS bounce to settle before any further suite run (mid-suite DS bounce fakes anchor-mismatch failures).

- [ ] **Step 6: Push**

Run: `git push`

---

### Task 6: Non-committing preview diff

**Files:**
- Create: `ops/audit/boot_utility_preview_diff.py`

- [ ] **Step 1: Write the reporter (prints only; writes no table)**

Create `ops/audit/boot_utility_preview_diff.py`:

```python
"""Preview which boots the ON path would change vs the committed OFF output.

Prints a champ x mode x comp -> (off_boot -> on_boot) report. Writes NO table
file - purely advisory so the operator can eyeball before deciding to flip
assume_boot_utility default-ON. Run: python ops/audit/boot_utility_preview_diff.py
"""
from __future__ import annotations

from core.build_order import _select_boots
from core.build_order_precompute import COMP_BIAS, SEED_CHAMPIONS  # sample + comp grid

ARCHES = ["marksman", "mage", "assassin", "tank", "enchanter", "bruiser"]
MODES = ["SR", "ARAM", "CHERRY"]


def main() -> None:
    changes = 0
    for arch in ARCHES:
        for comp, bias in COMP_BIAS.items():
            ad = float(bias.get("enemy_ad_share", 0.5))
            ap = float(bias.get("enemy_ap_share", 0.5))
            armor = float(bias.get("target_armor", 0.0))
            mr = float(bias.get("target_mr", 0.0))
            for mode in MODES:
                off, _ = _select_boots(arch, armor, mr, mode=mode,
                                       enemy_ad_share=ad, enemy_ap_share=ap,
                                       assume_boot_utility=False)
                on, _ = _select_boots(arch, armor, mr, mode=mode,
                                      enemy_ad_share=ad, enemy_ap_share=ap,
                                      assume_boot_utility=True)
                if off != on:
                    changes += 1
                    print(f"{arch:10s} {mode:7s} {comp:16s}  {off} -> {on}")
    print(f"\n{changes} boot changes if flipped default-ON.")


if __name__ == "__main__":
    main()
```

Verify `SEED_CHAMPIONS` / `COMP_BIAS` import names against `core/build_order_precompute.py` before running; drop the unused `SEED_CHAMPIONS` import if the arch-grid is enough (it is - remove it to keep ruff clean).

- [ ] **Step 2: Run it and capture the report**

Run: `python ops/audit/boot_utility_preview_diff.py`
Expected: a list of arch x mode x comp boot changes + a total. Save the output for the operator (paste into the session / scratchpad).

- [ ] **Step 3: py_compile + commit**

Run: `python -m py_compile ops/audit/boot_utility_preview_diff.py`
Then:

```bash
git add ops/audit/boot_utility_preview_diff.py
git commit -m "chore(ds): boot-utility preview-diff reporter (non-committing)"
git push
```

---

## Self-Review

**Spec coverage:** every spec section maps to a task - primitive + module home (Task 1), `_select_boots` OFF-byte-identical + ON argmax (Task 2), `plan_build_order` threading + comp signal (Task 3), ENGINE bump (Task 4), dual suite + Share + restart (Task 5), preview diff (Task 6). Fail-soft + hysteresis + Arena mirror + the 7 acceptance tests are all covered.

**Placeholder scan:** no TBD/TODO; every code step shows full code; the "verify the stub row shape / import names" notes are grounding checks, not deferred work.

**Type consistency:** `comp_weights`/`score_boot`/`select_boot`/`SELECTABLE_TIER2` names + signatures are identical across Tasks 1-3 and the consumer. `_select_boots` param order is stable Task 2 -> Task 3. `assume_boot_utility` default False everywhere.

**Known follow-ups (out of scope):** default-ON flip, real per-champion CC threading, enhancement #1 (situational alt-builds).
