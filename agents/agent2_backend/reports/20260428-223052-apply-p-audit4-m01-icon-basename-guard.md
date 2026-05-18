# Agent 2 - Task Report
**Task:** `t-2bfd8b567cb8` - `apply-proposal-p-audit4-m01-icon-basename-guard`
**Date:** 2026-04-28
**Proposal:** `P-audit4-m01-icon-basename-guard` (medium)

## Result: no code change required - fix already landed

`lib/icons/downloader.py` already contains the full fix, applied in commit
`70d3ba9` ("audit batch 9: round-4 audit findings (M-01, M-03, M-04, L-03)").

## What was verified

The file contains `_safe_basename()` (lines 36-58) which is **stronger** than
the audit's suggested one-liner:

| Check | Audit suggestion | Landed implementation |
|---|---|---|
| Path separators (`/`, `\`) | `"/" in img or "\\" in img` | same |
| Leading dot | `img.startswith(".")` | same + rejects `".."` and `"..."` |
| Control chars / null bytes | not specified | strips + rejects if changed |
| Windows drive paths (`C:foo`) | not specified | `os.path.basename(img) != img` |

The guard is called in all three vulnerable sites:

```
champions()  line 92:  bn = _safe_basename(img) if img else None
spells()     line 109: bn = _safe_basename(img) if img else None
items()      line 126: bn = _safe_basename(img) if img else None
```

On rejection the code logs `"rejecting suspicious <kind> icon name %r for %s"`
and `continue`s - no path write occurs.

Runes continue to use `Path(icon).name` (lines 145, 154) as noted in the
audit; those are untouched.

## Syntax check

```
python -m py_compile lib/icons/downloader.py  → OK
```

## No further action needed
