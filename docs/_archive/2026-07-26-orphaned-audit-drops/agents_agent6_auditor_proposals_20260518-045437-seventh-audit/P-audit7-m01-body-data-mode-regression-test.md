# P-audit7-m01 - `body[data-mode]` flap regression test

**Target agent:** Agent 3 (testing)
**Severity:** MEDIUM
**Filed by:** Agent 6, audit pass 2026-05-18 04:54 UTC

## Context

Commit `e4b08ba` ("fix(dashboard): stop body[data-mode] flap during
lobby preflip") closes a real visual flicker on the mode chip when the
LCU phase moves to ChampSelect ahead of the liveclient flip. The s153/
s157 pre-flip mirror dual-writes mode-key across HTTP + WS paths, and
the flap appeared at the seam between the two.

No regression test landed alongside the fix.

## Proposed test

`tests/preflip_mode/test_body_data_mode_no_flap.py`:

```python
"""Regression: e4b08ba - body[data-mode] must not flap during lobby preflip.

If the LCU has flipped to ChampSelect but the liveclient hasn't yet
caught up, build_state() must emit a stable mode-key on consecutive
calls so the dashboard's body[data-mode] attribute does not flicker.
"""
import unittest
from dashboard._state_builder import build_state


class BodyDataModeNoFlapTests(unittest.TestCase):
    def test_consecutive_calls_in_preflip_window_emit_same_mode(self):
        # Construct a state shape where LCU is ChampSelect but
        # liveclient is still null - the exact preflip window.
        lcu_snapshot = {"phase": "ChampSelect", "champ_select": {...}}
        liveclient_snapshot = None  # not yet visible

        state_a = build_state(
            lcu=lcu_snapshot,
            liveclient=liveclient_snapshot,
            coach=None,
        )
        state_b = build_state(
            lcu=lcu_snapshot,
            liveclient=liveclient_snapshot,
            coach=None,
        )
        self.assertEqual(state_a["mode_key"], state_b["mode_key"])
        self.assertNotEqual(state_a["mode_key"], "client")
        # The fix routes preflip to the resolved CS mode, not to
        # the stale liveclient-null "client" default.


if __name__ == "__main__":
    unittest.main()
```

(Agent 3: snap the exact `build_state()` kwargs from existing
preflip tests; the shape above is illustrative.)

## Why MEDIUM, not LOW

The dual-write s153/s157 pattern means *any* future change to either
HTTP or WS state-builder path can re-introduce the flap silently. The
e4b08ba commit shows it has happened once already after 6 months of
stable behavior - the regression risk is real.

## Acceptance

- [ ] Test added under `tests/preflip_mode/`.
- [ ] Test fails on the pre-`e4b08ba` revision (verify by `git
      stash`-ing the fix and re-running).
- [ ] Test passes on current `main`.

## Note

The untracked `tests/preflip_mode/test_file_ingest_mirror.py` at session
start may be the operator's WIP for this exact test - Agent 3 should
check before writing a duplicate. Audit7-L-01 flags that as a separate
matter for operator decision.
