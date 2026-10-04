"""RM-195: the last two of four zero-reference module functions are deleted.

`core/theme.py` `strip_tags` and `core/vision_token.py`
`is_using_legacy_fallback` (an always-False shim for a fallback retired
2026-04-28) had no caller of any kind - no import site, no string literal,
no getattr - measured 2026-10-04. The other two RM-195 symbols are NOT dead:
`detect_lane_roam_window` is registered into the detector registry in
`core/decision_detector.py` and iterated by production code, and
`reset_support_route_override_cache` has a test caller. Do not delete those.
"""

import core.decision_detector as decision_detector
import core.ds_support_route_overrides as ds_support_route_overrides
import core.theme as theme
import core.vision_token as vision_token


def test_dead_symbols_are_gone():
    assert not hasattr(theme, "strip_tags")
    assert not hasattr(vision_token, "is_using_legacy_fallback")


def test_live_siblings_are_kept():
    assert callable(decision_detector.detect_lane_roam_window)
    assert callable(ds_support_route_overrides.reset_support_route_override_cache)
