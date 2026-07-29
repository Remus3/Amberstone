"""Sync RC institutional knowledge into the Perseus Vault memory store.

Perseus Vault is the local, no-cloud semantic-recall layer that stops agents from
redoing closed work, re-pitching refuted ideas, or acting on stale docs. It is a
MIRROR, never a source of truth: the source of truth stays CLAUDE.md / the
`memory/*.md` files / docs/LEDGER.md / ROADMAP.md / BACKLOG.md. Re-run this after
any of those change so recall cannot drift stale.

Sources, highest signal first:
  1. CLAUDE.md "### Settled - do not re-litigate"  -> category 'settled' (always-on)
  2. ~/.claude/projects/C--Riot-Commander/memory/  -> category = frontmatter type
  3. docs/LEDGER.md numbered items                 -> category 'ledger'
  4. ROADMAP.md / BACKLOG.md sections              -> 'roadmap' / 'backlog'

Writes are idempotent: category+key identifies an entity, so a re-run updates in
place instead of duplicating. Near-duplicate merging is disabled on every write
because LEDGER rows share heavy boilerplate ("DONE ... Tier-1 ... ENGINE-IMPACT
NONE") and would otherwise be silently collapsed into each other.

Embeddings are NOT written by the remember path - they are backfilled afterwards.
Skipping the backfill leaves `semantic_recall: available` and `status: healthy`
reported while most rows have no vector, so recall silently degrades to keyword.
This script always backfills and then asserts embedded == active.

Usage:
    python tools/perseus_sync.py            # full sync + backfill + verify
    python tools/perseus_sync.py --verify   # report coverage only, write nothing
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

PERSEUS_HOME = os.path.join(os.path.expanduser("~"), ".perseus-vault")
PV = os.path.join(PERSEUS_HOME, "bin", "perseus-vault.exe")
DB = os.path.join(PERSEUS_HOME, "data", "perseus-vault.db")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMDIR = os.path.join(
    os.path.expanduser("~"), ".claude", "projects", "C--Riot-Commander", "memory"
)

IMPORTANCE = {"user": 0.95, "feedback": 0.9, "project": 0.8, "reference": 0.75}
ETYPE = {
    "feedback": "convention",
    "reference": "reference",
    "project": "insight",
    "user": "insight",
}
BACKFILL_CATEGORIES = [
    "ledger",
    "project",
    "reference",
    "feedback",
    "settled",
    "backlog",
    "roadmap",
    "user",
]


class Vault:
    """Minimal MCP stdio client for one long-lived perseus-vault serve process."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [PV, "serve", "--db", DB],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._id = 0
        self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "perseus_sync", "version": "1"},
            },
        )
        self._notify("notifications/initialized", {})

    def _notify(self, method: str, params: dict) -> None:
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        )
        self.proc.stdin.flush()

    def rpc(self, method: str, params: dict):
        self._id += 1
        self.proc.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
            )
            + "\n"
        )
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def call(self, tool: str, args: dict):
        return self.rpc("tools/call", {"name": tool, "arguments": args})

    def health(self) -> dict:
        res = self.call("perseus_vault_health", {})
        return json.loads(res["result"]["content"][0]["text"])

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        finally:
            self.proc.terminate()


def slugify(text: str, limit: int = 70) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (text[:limit] or "x").strip("-")


def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def settled_blocks(claude_md: str) -> list[str]:
    """Top-level bullets of the CLAUDE.md Settled section, continuations attached."""
    match = re.search(
        r"^### Settled[^\n]*\n(.*?)(?=\n^#{1,3} |\Z)", claude_md, re.S | re.M
    )
    if not match:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in match.group(1).splitlines():
        if line.startswith("- "):
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
        elif current and line.strip():
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if len(b) > 40]


def parse_memory_file(path: str) -> tuple[str, str, str, str]:
    """Return (name, description, type, body) for a memory .md file."""
    raw = read_text(path)
    name = os.path.basename(path)[:-3]
    description, mtype, body = "", "reference", raw
    front = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if front:
        head, body = front.group(1), front.group(2)
        m_name = re.search(r"^name:\s*(.+)$", head, re.M)
        m_desc = re.search(r"^description:\s*(.+)$", head, re.M)
        m_type = re.search(r"^\s*type:\s*(\w+)\s*$", head, re.M)
        if m_name:
            name = m_name.group(1).strip().strip('"')
        if m_desc:
            description = m_desc.group(1).strip().strip('"')
        if m_type:
            mtype = m_type.group(1).strip()
    if mtype not in IMPORTANCE:
        mtype = "reference"
    return name, description, mtype, body.strip()


def sync(vault: Vault) -> dict:
    counts = {"settled": 0, "memory": 0, "ledger": 0, "sections": 0}
    failures: list[str] = []

    def remember(category, key, content, summary, tags, importance, topic, etype):
        body = {"content": content}
        if summary:
            body["summary"] = summary
        res = vault.call(
            "perseus_vault_remember",
            {
                "category": category,
                "key": key[:180],
                "body_json": json.dumps(body, ensure_ascii=False),
                "tags": tags,
                "importance": importance,
                "topic_path": topic,
                "type": etype,
                "skip_dedup": True,
            },
        )
        if (res or {}).get("error") or (res or {}).get("result", {}).get("isError"):
            if len(failures) < 15:
                failures.append(f"{category}/{key}")
            return False
        return True

    # 1. Settled - written via the CLI so --always-on can be set.
    for block in settled_blocks(read_text(os.path.join(REPO, "CLAUDE.md"))):
        key = slugify(re.sub(r"[*`]", "", block[2:140]))
        body = json.dumps(
            {
                "content": block,
                "summary": "CLAUDE.md Settled: do NOT re-litigate this.",
            },
            ensure_ascii=False,
        )
        proc = subprocess.run(
            [
                PV, "write", "--db", DB,
                "--category", "settled", "--key", key, "--body", body,
                "--tags", "settled,do-not-relitigate,claude-md",
                "--importance", "0.98", "--entity-type", "decision", "--always-on",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0:
            counts["settled"] += 1
        else:
            failures.append(f"settled/{key}")

    # 2. Memory files.
    if os.path.isdir(MEMDIR):
        for filename in sorted(os.listdir(MEMDIR)):
            if not filename.endswith(".md") or filename == "MEMORY.md":
                continue
            name, desc, mtype, body = parse_memory_file(os.path.join(MEMDIR, filename))
            if remember(
                mtype, slugify(name), body, desc,
                [mtype, "rc-memory"], IMPORTANCE[mtype],
                f"rc/memory/{mtype}", ETYPE[mtype],
            ):
                counts["memory"] += 1

    # 3. LEDGER items.
    ledger_path = os.path.join(REPO, "docs", "LEDGER.md")
    if os.path.exists(ledger_path):
        for match in re.finditer(r"^(\d{1,5})\.\s+(.+)$", read_text(ledger_path), re.M):
            number, text = match.group(1), match.group(2).strip()
            if len(text) < 30:
                continue
            if remember(
                "ledger", f"item-{number}", text, re.sub(r"[*`]", "", text)[:300],
                ["ledger", "shipped", "already-done"], 0.45, "rc/ledger", "reference",
            ):
                counts["ledger"] += 1

    # 4. ROADMAP / BACKLOG sections.
    for filename, category in (("ROADMAP.md", "roadmap"), ("BACKLOG.md", "backlog")):
        path = os.path.join(REPO, filename)
        if not os.path.exists(path):
            continue
        parts = re.split(r"^(#{2,4} .+)$", read_text(path), flags=re.M)
        for index in range(1, len(parts), 2):
            heading = parts[index].lstrip("# ").strip()
            chunk = (parts[index + 1] if index + 1 < len(parts) else "").strip()
            if len(chunk) < 60:
                continue
            if remember(
                category, slugify(heading), (parts[index] + "\n" + chunk)[:8000],
                heading, [category, "open-work"], 0.7, f"rc/{category}", "reference",
            ):
                counts["sections"] += 1

    counts["failures"] = failures
    return counts


def backfill(vault: Vault) -> tuple[int, int]:
    """Embed every entity lacking a vector. Returns (embedded, active)."""
    stall = 0
    while True:
        before = vault.health()["embedded_memories"]
        for category in BACKFILL_CATEGORIES:
            vault.call(
                "perseus_vault_embed",
                {"batch_category": category, "batch_limit": 500},
            )
        health = vault.health()
        done, total = health["embedded_memories"], health["active_memories"]
        if done >= total:
            return done, total
        if done == before:
            stall += 1
            if stall >= 2:
                return done, total
        else:
            stall = 0


def main() -> int:
    if not os.path.exists(PV):
        print(f"perseus-vault binary not found at {PV}", file=sys.stderr)
        return 2

    verify_only = "--verify" in sys.argv
    vault = Vault()
    try:
        if verify_only:
            health = vault.health()
            done = health["embedded_memories"]
            total = health["active_memories"]
            print(f"active={total} embedded={done}")
            if done < total:
                print(f"STALE: {total - done} entities lack embeddings", file=sys.stderr)
                return 1
            print("OK: embedding coverage complete")
            return 0

        started = time.time()
        counts = sync(vault)
        done, total = backfill(vault)
        print(
            "perseus sync: settled={settled} memory={memory} ledger={ledger} "
            "sections={sections}".format(**counts)
        )
        print(f"embedded={done}/{total} in {time.time() - started:.0f}s")
        if counts["failures"]:
            print(f"write failures: {counts['failures']}", file=sys.stderr)
            return 1
        if done < total:
            print(
                f"embedding backfill incomplete: {total - done} missing",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        vault.close()


if __name__ == "__main__":
    raise SystemExit(main())
