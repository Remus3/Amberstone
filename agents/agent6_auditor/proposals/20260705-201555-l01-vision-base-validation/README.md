# L-01 vision-calibrator base validation

**Severity:** low  
**Owner:** Agent 2 (backend)  
**Filed by:** Agent 6 twelfth audit (2026-07-05)  
**Report:** `agents/agent6_auditor/reports/20260705-201555-twelfth-audit-phase3.md`

## Problem

`dashboard/routes_vision_calibrator.py:_save_profile_from_body`
validates `regions` via `validate_regions()` but forwards
`body.get("base")` unchecked to `core.vision_profiles.save_profile`,
which writes `list(base)` verbatim. A malformed base (None, wrong
length, negative, huge, non-numeric) persists and later becomes
divisor state in `_profile_regions_payload._scale_regions()` on the
legacy-seed path.

Today the legacy-seed reader is defensively guarded, but the
invariant is fragile - a future reader without those guards will
divide by zero or scale wrong.

## Fix

Add a `validate_base(base)` guard in `core/vision_profiles.py` and
call it from the route BEFORE `save_profile`.

## Unified diff (proposed)

```diff
--- a/core/vision_profiles.py
+++ b/core/vision_profiles.py
@@
 def _safe(config_key: str) -> str:
     return re.sub(r"[^A-Za-z0-9._-]", "_", str(config_key))[:120] or "unknown"
+
+
+_BASE_MAX = 10000
+
+
+def validate_base(base):
+    """Validate a profile base [width, height]. Returns (ok, err, clean).
+    Rejects None, wrong length, non-numeric, non-positive, or huge."""
+    if not isinstance(base, (list, tuple)) or len(base) != 2:
+        return (False, "base must be [width, height]", None)
+    coords = []
+    for c in base:
+        if isinstance(c, bool) or not isinstance(c, (int, float)):
+            return (False, "base coordinates must be numbers", None)
+        v = int(c)
+        if v <= 0 or v > _BASE_MAX:
+            return (False, "base out of range", None)
+        coords.append(v)
+    return (True, None, coords)
```

```diff
--- a/dashboard/routes_vision_calibrator.py
+++ b/dashboard/routes_vision_calibrator.py
@@
 def _save_profile_from_body(h, body) -> None:
-    """Validate then save a per-profile region set. An invalid payload returns
-    400 and never calls save_profile (mirrors the legacy save_regions guard)."""
+    """Validate regions + base then save a per-profile set. An invalid
+    payload returns 400 and never calls save_profile."""
     ok, err, clean = validate_regions(body.get("regions"))
     if not ok:
         _send_json(h, 400, {"ok": False, "error": err})
         return
-    base = body.get("base")
+    ok_b, err_b, base = vp.validate_base(body.get("base"))
+    if not ok_b:
+        _send_json(h, 400, {"ok": False, "error": err_b})
+        return
     res = vp.save_profile(vp.active_config_key(), clean, base)
```

## Tests to add

Extend `tests/test_vision_calibrator_profile.py`:
- POST `{"regions": {...ok...}, "base": None, "source": "profile"}` -> 400
- POST `{"regions": {...ok...}, "base": [0, 0]}` -> 400
- POST `{"regions": {...ok...}, "base": [1920]}` -> 400
- POST `{"regions": {...ok...}, "base": [1920, "1080"]}` -> 400
- POST `{"regions": {...ok...}, "base": [-1, 1080]}` -> 400
- POST `{"regions": {...ok...}, "base": [1920, 1080]}` -> 200 (regression)

## Risk

None. Well-behaved calibrator clients always send
`[frame.width, frame.height]` from `/api/vision-frame`, so the tighter
guard rejects only malformed payloads that would break a future
reader.
