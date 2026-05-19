#!/usr/bin/env python3
"""PostToolUse pytest gate.

Reads the Claude Code PostToolUse hook payload on stdin and decides whether to
run the full pytest suite. Docs-only edits (every touched path is *.md, *.txt,
or lives under a docs/ tree) skip the suite; any code-path edit runs it.

Semantics match the prior inline hook exactly: combined pytest output is
tailed to the last 20 lines and the gate always exits 0 (informational, not
blocking), so a red suite is surfaced as text without aborting the tool.
"""
import json
import subprocess
import sys

CODE_SKIP_SUFFIXES = (".md", ".txt")


def _is_docs_only(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    if p.endswith(CODE_SKIP_SUFFIXES):
        return True
    return "/docs/" in p or p.startswith("docs/")


def _collect_paths(payload: dict) -> list:
    ti = payload.get("tool_input") or {}
    paths = []
    for key in ("file_path", "notebook_path"):
        v = ti.get(key)
        if isinstance(v, str) and v:
            paths.append(v)
    edits = ti.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                paths.append(e["file_path"])
    return paths


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}

    paths = _collect_paths(payload)
    # Unknown shape -> do not skip (fail safe: still run the suite).
    if paths and all(_is_docs_only(p) for p in paths):
        print("[pytest_guard] docs-only edit (%s) - suite skipped"
              % ", ".join(paths))
        return 0

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "--ff", "-q"],
        capture_output=True,
        text=True,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = combined.splitlines()[-20:]
    sys.stdout.write("\n".join(tail) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
