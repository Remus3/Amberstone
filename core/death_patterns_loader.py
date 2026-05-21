"""core/death_patterns_loader.py - read postmortem JSON, format coach context.

Reads `data/coaching/death_patterns.json` (written by
`scripts/postmortem_analyze.py`, ADR-007 phase 2) and renders the top-3
death patterns as a short PERSONAL CONTEXT block for the four mode coach
system prompts.

Fail-soft contract: every helper returns "" / [] when the file is missing,
malformed, or contains no top-3. Coaches always call into this module; an
absent JSON degrades gracefully to "no personalization", same as before
ADR-007 phase 2 shipped.
"""
from __future__ import annotations

import json
import pathlib

_DEFAULT_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "coaching" / "death_patterns.json"


def _safe_load(path: pathlib.Path) -> dict:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def top_patterns(path: pathlib.Path | None = None) -> list[dict]:
    """Return the top-3 patterns as a list of {key, label, description, count}.

    Empty list when the JSON is missing/malformed or no patterns fired.
    """
    data = _safe_load(path or _DEFAULT_PATH)
    if not isinstance(data, dict):
        return []
    top3 = data.get("top3") or []
    patterns = data.get("patterns") or {}
    out: list[dict] = []
    for key in top3:
        meta = patterns.get(key)
        if not isinstance(meta, dict):
            continue
        out.append({
            "key": key,
            "label": meta.get("label", key),
            "description": meta.get("description", ""),
            "count": int(meta.get("count", 0)),
        })
    return out


def personal_context_block(path: pathlib.Path | None = None) -> str:
    """Format the top-3 patterns as a system-prompt-ready string block.

    Returns "" when no top-3 - safe to f-string into any prompt without
    a None / empty-block guard at the call site. The block is APPENDED
    to existing prompts so the cached prefix above stays byte-identical.
    """
    patterns = top_patterns(path)
    if not patterns:
        return ""
    lines = [
        "",
        "PERSONAL CONTEXT (operator's recurring death patterns from rewind_history.db):",
    ]
    for i, p in enumerate(patterns, start=1):
        lines.append(f"  {i}. {p['label']} ({p['count']}x): {p['description']}")
    lines.append("Calibrate advice to these recurring mistakes when applicable.")
    return "\n".join(lines)
