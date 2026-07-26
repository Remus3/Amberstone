# Decision - P-audit6-m01-bbox-override-validate

**Decided by:** Agent 2 (Backend)
**Decision date:** 2026-05-12
**Proposal severity:** MEDIUM
**Outcome:** ACCEPTED - shipped

## What was proposed

Unify the `?bbox=` HTTP override parsing path in
`agents/supervisor.py:_handle_minimap_crop` with the bounds-validity checks
already enforced by `agents/_minimap_bbox.load_persisted()`:

- `r > l` and `b > t` (reject degenerate or inverted boxes)
- All coordinates in `[0, 10000]` (reject out-of-range values)
- Return HTTP 400 with a descriptive error on any violation

The old code accepted any 4-int tuple, letting PIL silently return degenerate
images and letting extreme coordinates clip to full-frame - defeating the
purpose of the override.

## Changes made

### `agents/_minimap_bbox.py` - new `parse_http_override(raw)` helper

Rather than inlining the validation in the handler (the proposal's diff),
I extracted it into a dedicated function in `_minimap_bbox.py`. This module
already owns all bbox validation logic (`load_persisted` has the same checks),
so consolidating here avoids the supervisor import graph in tests and gives a
single authoritative contract for bbox validity.

```python
def parse_http_override(raw: str) -> tuple[int, int, int, int]:
    """Parse and validate a ?bbox=x1,y1,x2,y2 query-string value.
    Raises ValueError (with message) on any violation."""
```

### `agents/supervisor.py:596-605` - handler now calls `parse_http_override`

Old:
```python
try:
    parts = [int(x) for x in bbox_raw.split(",")]
    if len(parts) == 4:
        bbox = tuple(parts)
    else:
        raise ValueError
except ValueError:
    self._send_json(400, {"error": "bbox must be x1,y1,x2,y2"})
    return
```

New (simplified handler - validation logic lives in `_minimap_bbox`):
```python
try:
    from agents._minimap_bbox import parse_http_override as _parse_bbox
    bbox = _parse_bbox(bbox_raw)
except ValueError as ve:
    self._send_json(
        400,
        {"error": f"bbox must be x1,y1,x2,y2 with r>l,b>t,coords in [0,10000]: {ve}"},
    )
    return
```

### `tests/fu01_minimap/test_http_override.py` - new, closes L-01

10 bad-input cases (each `ValueError`), 4 good-input cases with equality
assertions, plus 3 boundary tests. Run via `pytest tests/fu01_minimap/ -q`.

## Verification

```
compile ok
25 passed, 14 subtests passed in 0.04s
```

19 pre-existing FU01 tests remain green. 6 new test functions (14 subtests).

## Deviation from proposal diff

The proposal inlined validation directly in the handler. This decision instead
extracted it into `_minimap_bbox.parse_http_override()`. Effect is identical
from the HTTP contract perspective; the extraction is strictly better for
testability and consolidates the two bbox validation paths into one module.

## Audit findings closed

- **M-01** - HTTP `?bbox=` override skips bounds-validity check → CLOSED
- **L-01** - `tests/fu01_minimap/` has zero coverage of HTTP override path → CLOSED
