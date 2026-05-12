# P-audit6-m01 — `/api/minimap-crop` HTTP `?bbox=` override must validate r>l, b>t (and clamp coord range)

**Owner:** Agent 2
**Severity:** MEDIUM

## Problem

`agents/supervisor.py:596-605` parses the `?bbox=x1,y1,x2,y2` query
parameter and validates only (a) parseability as 4 ints, (b) exactly 4
elements. The persisted-calibration loader at
`agents/_minimap_bbox.py:66-68` additionally enforces `r > l` and
`b > t` (rejecting degenerate or inverted boxes).

Two consequences:

1. **Silent visual breakage.** `PIL.Image.crop()` is permissive; it
   accepts `(50, 50, 50, 100)` (zero-width) and inverted boxes without
   raising. The dashboard receives HTTP 200 with a degenerate/empty
   PNG and renders an empty overlay with no operator signal.
2. **Out-of-range coords go undetected.** `?bbox=-1e6,-1e6,2e6,2e6`
   silently clips to full-frame at `Image.crop()` time, defeating the
   intent of the override entirely. There's no caller-side feedback
   that the values were nonsensical.

Trust boundary is dashboard-internal Tailnet HTTP — not externally
exposed — so this is defense-in-depth, not production-blocking. Real
defect: the two paths (HTTP override, persisted file) should enforce
the same contract on the `bbox` tuple they hand to `Image.crop()`.

Audit-6 finding L-01 (`tests/fu01_minimap/` has zero coverage of the
HTTP override path) folds in here: the test added with this fix
closes both M-01 and L-01.

## Fix (unified diff)

```diff
--- a/agents/supervisor.py
+++ b/agents/supervisor.py
@@ -593,15 +593,21 @@ class _Handler(BaseHTTPRequestHandler):
         # Bbox resolution order: ?bbox= override → persisted calibration in
         # data/vision_regions.json (`_minimap_<mode>` key) → hardcoded
         # 1920×1080 fallback. Arena has no minimap — falls through to 404.
         if bbox_raw:
             try:
                 parts = [int(x) for x in bbox_raw.split(",")]
-                if len(parts) == 4:
-                    bbox = tuple(parts)
-                else:
+                if len(parts) != 4:
+                    raise ValueError("must have 4 elements")
+                l, t, r, b = parts
+                if r <= l or b <= t:
+                    raise ValueError("r<=l or b<=t")
+                if not all(0 <= c <= 10000 for c in parts):
+                    raise ValueError("coord out of range [0, 10000]")
+                bbox = (l, t, r, b)
+            except ValueError as ve:
+                self._send_json(
+                    400,
+                    {"error": f"bbox must be x1,y1,x2,y2 with r>l,b>t,coords in [0,10000]: {ve}"},
+                )
                 return
-            except ValueError:
-                self._send_json(400, {"error": "bbox must be x1,y1,x2,y2"})
-                return
         else:
             from agents._minimap_bbox import resolve as _resolve_minimap_bbox
             bbox = _resolve_minimap_bbox(mode)
```

Note the indentation of the `return` — it must move into the `except`
block (currently it's the trailing line of the outer `try`). Verify
before submitting.

## Test

Add to `tests/fu01_minimap/test_http_override.py` (new file) or fold
into the existing test module:

```python
import io
from http.server import BaseHTTPRequestHandler
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse, parse_qs

# Helper: construct a mock handler with a synthesized GET query string,
# capture the response status + JSON body, assert HTTP 400 on each bad input.
BAD_INPUTS = [
    "50,50,50,100",          # degenerate (l==r)
    "100,50,50,100",         # inverted (r<l)
    "0,0,1920,0",            # degenerate (t==b)
    "-1,0,100,100",          # negative coord
    "0,0,1000000,1000000",   # out-of-range coord
    "0,0,100",               # too few elements
    "0,0,100,100,100",       # too many elements
    "a,b,c,d",               # non-numeric
    "",                      # empty (handled by other path; should resolve)
]

GOOD_INPUTS = [
    "1565,735,1905,1075",    # the hardcoded SR default
    "0,0,1,1",               # tiny but valid
    "0,0,10000,10000",       # max valid range
]

# Assert: each BAD_INPUT yields HTTP 400; each GOOD_INPUT yields HTTP 200
# (mocking vision_server response). Match status code + error message
# pattern; do not assert on image bytes.
```

## Notes

- The integer-range clamp (10000) is generous — well beyond any
  realistic display resolution but small enough that an unbounded
  coord can't waste memory inside PIL during the crop. Adjust upward
  if a 4K/8K case ever lands.
- After applying, `py_compile agents/supervisor.py` and run the FU01
  test directory: `python -m pytest tests/fu01_minimap/ -q`.
- The 19 existing FU01 tests should remain green — this change is
  in the supervisor handler, not the resolver.
