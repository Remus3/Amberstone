# arch: compact projection over Perseus Vault recall | section=tools | frozen=no
"""Compact recall over the Perseus Vault - category / key / summary only.

CLAUDE.md makes "recall before starting any non-trivial item" mandatory. The
raw MCP recall response works directly against that rule: each hit carries the
full entity body TWICE (``content`` and ``body_json``), and LEDGER entities
routinely run to several kilobytes. A four-hit query can cost thousands of
tokens of context for what is nearly always a three-field answer - did someone
already close this, and where is it written down.

Left unfixed, the mandatory step is expensive enough to get skipped, which
defeats the store. This projection is what keeps it affordable.

Usage:
    python tools/perseus_recall.py "did we already decide X?"
    python tools/perseus_recall.py "topic" --limit 5 --category settled
    python tools/perseus_recall.py "topic" --json

Reading a full body is a deliberate second step: take the key from the compact
listing and fetch that one entity.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

PERSEUS_HOME = os.path.join(os.path.expanduser("~"), ".perseus-vault")
PV = os.path.join(PERSEUS_HOME, "bin", "perseus-vault.exe")
DB = os.path.join(PERSEUS_HOME, "data", "perseus-vault.db")

# perseus-vault.exe is a CONSOLE-subsystem binary (PE Subsystem=3), so a
# parent WITHOUT a console of its own gets a new console window allocated
# for it. Latent today - these tools run from a console-bearing parent - but
# scheduling any of them under pythonw would surface the flash measured in
# claude_quota_watch.py on 2026-08-01. Flagged now so that never happens.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

DEFAULT_CHARS = 220
NO_HITS = "(no hits)"


def _first_line(text: str) -> str:
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def project(items, chars: int = DEFAULT_CHARS) -> list[dict]:
    """Recall hits -> [{category, key, summary}], dropping every raw body.

    Tolerates malformed hits rather than raising: this runs at the start of
    real work, and a bad row must not derail the task it is informing.
    """
    rows: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict) or not item:
            continue
        summary = _first_line(item.get("summary") or "")
        if not summary:
            # No summary: fall back to the body's own content field, then to
            # the raw content, so a hit is never rendered blank.
            body = item.get("body_json")
            if isinstance(body, str):
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict):
                        summary = _first_line(parsed.get("content") or "")
                except (json.JSONDecodeError, ValueError):
                    summary = ""
            if not summary:
                summary = _first_line(item.get("content") or "")
        rows.append({
            "category": item.get("category") or "?",
            "key": item.get("key") or "?",
            "summary": summary[:chars],
        })
    return rows


def format_lines(rows: list[dict]) -> str:
    """Exactly one line per hit.

    Deliberately not a prettier two-line block: this tool exists to make the
    mandatory recall step cheap, and a listing that doubles in height for
    readability is spending the thing it was written to save.
    """
    if not rows:
        return NO_HITS
    return "\n".join(
        f"[{row['category']}] {row['key']} :: {row['summary']}" for row in rows
    )


def recall(
    query: str,
    limit: int = 8,
    mode: str = "hybrid",
    category: str | None = None,
    chars: int = DEFAULT_CHARS,
) -> list[dict]:
    """Query the vault over MCP stdio and return projected rows."""
    if not os.path.exists(PV):
        raise FileNotFoundError(f"perseus-vault binary not found at {PV}")

    proc = subprocess.Popen(
        [PV, "serve", "--db", DB],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )
    counter = [0]

    def rpc(method, params):
        counter[0] += 1
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": counter[0], "method": method, "params": params,
        }) + "\n")
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    try:
        rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "perseus_recall", "version": "1"},
        })
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }) + "\n")
        proc.stdin.flush()

        args = {"query": query, "limit": limit, "mode": mode}
        if category:
            args["category"] = category
        response = rpc("tools/call", {
            "name": "perseus_vault_recall", "arguments": args,
        })
        if not response or "result" not in response:
            return []
        payload = json.loads(response["result"]["content"][0]["text"])
        return project(payload.get("items"), chars=chars)
    finally:
        try:
            proc.stdin.close()
        finally:
            proc.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", help="what you are about to work on, in your words")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--mode", default="hybrid", choices=["fts5", "dense", "hybrid"])
    parser.add_argument("--category", default=None,
                        help="restrict to one category, e.g. settled / ledger")
    parser.add_argument("--chars", type=int, default=DEFAULT_CHARS)
    parser.add_argument("--json", action="store_true", help="emit projected JSON")
    parsed = parser.parse_args()

    try:
        rows = recall(
            parsed.query, limit=parsed.limit, mode=parsed.mode,
            category=parsed.category, chars=parsed.chars,
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2

    if parsed.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(format_lines(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
