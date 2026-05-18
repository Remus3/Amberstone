# Task Report - P-audit3-m02: DDragon cache-read JSONDecodeError guard

- **Task id:** `t-439eac71cab8`
- **Operation:** `apply-proposal-p-audit3-m02-ddragon-cache-parse-guard`
- **Agent:** agent2 (Backend / Charter)
- **Completed:** 2026-04-22T14:24:13Z
- **Result:** NO-OP - fix already applied

## Finding

`lib/ddragon/fetch.py` already contains the full fix described in proposal
P-audit3-m02.  The code was applied (presumably by an earlier agent session)
and includes:

1. **Audit comment** (lines 79–82) explicitly citing P-audit3-m02 and the
   rationale (corrupt/partial cache used to crash coaches on first call).

2. **`_read_cached` helper** (lines 83–93) centralising all four cache reads:
   ```python
   def _read_cached(self, name: str):
       p = self._cached(name)
       if not p.exists():
           return None
       try:
           return json.loads(p.read_text(encoding="utf-8"))
       except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
           logger.warning(
               "ddragon cache %s corrupt (%s) - re-pulling", p.name, e,
           )
           return None
   ```

3. **All four bundle methods** (`champions`, `items`, `runes`,
   `summoner_spells`) - lines 95–121 - route through `_read_cached()` instead
   of the former bare `json.loads(p.read_text())`.  A `None` return causes
   each method to fall through to `self._pull(name)`, re-fetching from CDN
   and atomically overwriting the corrupt file.

## Why the original report cited specific line numbers

The audit report (20260422-134400-third-audit-phase3.md) referenced the
pre-fix line numbers 82, 88, 94, 100.  Those four direct `json.loads` calls
have been refactored away entirely; the helper now lives at line 83 with a
single guarded read path.

## Verification

- `UnicodeDecodeError` is covered in addition to `JSONDecodeError` and
  `OSError`, guarding against half-written UTF-8 sequences left by a crash
  mid-write (even though `_atomic_write_json` uses `os.replace`, a third-party
  tool writing the cache directory directly would not).
- The `_pull` fallback path itself is safe: `_atomic_write_json` uses a `.tmp`
  intermediary and `os.replace`, so a network failure during re-pull leaves the
  (corrupt) original in place rather than truncating it further.

## Status

**CLOSED - already shipped.** No code changes required in this session.
