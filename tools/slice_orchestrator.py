#!/usr/bin/env python3
"""Crash-resilient slice manifest for parallel orchestrator runs.

The orchestrator-merge pattern (headless-upgrade) dispatches up to 100 worktree
slices per run. A single API socket drop, thinking-block 400, or cascade-cancel
can wipe an unattended run's progress because nothing durably records which
slices already verified + committed. This module persists that state to a JSON
manifest so a relaunch resumes from the last committed slice instead of redoing
everything.

Status lifecycle per slice:
    pending -> in_progress -> verified -> committed
                           \\-> failed (retry candidate)

The orchestrator marks a slice `verified` only after the read-only `verifier`
subagent confirms ground truth (see .claude/agents/verifier.md), then `committed`
after the merge + push land. On restart, `resume` lists every non-committed
slice so work already shipped is skipped and only the incomplete slices re-run.

CLI (every command takes --manifest to override the default path; tests inject a
tmp path):
    init    --run-id ID [--head SHA] [--force]
    add     --id S --title T [--files a,b,c]
    set     --id S --status STATUS [--commit SHA] [--note TEXT]
    status  [--id S]
    next                 # first work-needing slice id, or empty
    resume               # all non-committed slice ids, newest dispatch order
    summary              # counts per status as JSON

Exit 0 on success; exit 2 on user error (dup id, unknown slice, bad status,
manifest exists without --force).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MANIFEST = Path("ops/runtime/slice_manifest.json")

STATUSES = ("pending", "in_progress", "verified", "failed", "committed")
# Order in which `next` prefers work-needing slices: not-started, then a failed
# retry, then an interrupted-in-flight slice.
_NEXT_PRIORITY = ("pending", "failed", "in_progress")
# A restart must re-surface everything that is not durably shipped.
_INCOMPLETE = ("pending", "in_progress", "verified", "failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_manifest(path: Path) -> dict:
    """Return the manifest dict, or {} when the file is absent/unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(path: Path, data: dict) -> None:
    """Atomic write: temp file in the same dir, then os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _find(data: dict, slice_id: str) -> dict | None:
    for s in data.get("slices", []):
        if s.get("id") == slice_id:
            return s
    return None


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    if path.exists() and not args.force:
        sys.stderr.write(f"manifest already exists: {path} (use --force to overwrite)\n")
        return 2
    data = {
        "run_id": args.run_id,
        "created_at": _now(),
        "head_sha": args.head or "",
        "slices": [],
    }
    save_manifest(path, data)
    print(json.dumps({"run_id": args.run_id, "manifest": str(path)}))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    data = load_manifest(path)
    if not data:
        sys.stderr.write(f"no manifest at {path} - run init first\n")
        return 2
    if _find(data, args.id) is not None:
        sys.stderr.write(f"slice id already exists: {args.id}\n")
        return 2
    files = [f.strip() for f in (args.files or "").split(",") if f.strip()]
    data["slices"].append(
        {
            "id": args.id,
            "title": args.title,
            "files": files,
            "status": "pending",
            "commit": None,
            "note": "",
            "updated_at": _now(),
        }
    )
    save_manifest(path, data)
    print(json.dumps({"added": args.id, "status": "pending"}))
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    data = load_manifest(path)
    sl = _find(data, args.id)
    if sl is None:
        sys.stderr.write(f"unknown slice id: {args.id}\n")
        return 2
    if args.status is not None:
        if args.status not in STATUSES:
            sys.stderr.write(
                f"bad status {args.status!r}; allowed: {', '.join(STATUSES)}\n"
            )
            return 2
        sl["status"] = args.status
    if args.commit is not None:
        sl["commit"] = args.commit
    if args.note is not None:
        sl["note"] = args.note
    sl["updated_at"] = _now()
    save_manifest(path, data)
    print(json.dumps({"id": args.id, "status": sl["status"], "commit": sl["commit"]}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.manifest)
    data = load_manifest(path)
    if args.id:
        sl = _find(data, args.id)
        if sl is None:
            sys.stderr.write(f"unknown slice id: {args.id}\n")
            return 2
        print(json.dumps(sl, indent=2))
    else:
        print(json.dumps(data, indent=2))
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    data = load_manifest(Path(args.manifest))
    slices = data.get("slices", [])
    for status in _NEXT_PRIORITY:
        for s in slices:
            if s.get("status") == status:
                print(s["id"])
                return 0
    print("")  # nothing left to work
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    data = load_manifest(Path(args.manifest))
    ids = [s["id"] for s in data.get("slices", []) if s.get("status") in _INCOMPLETE]
    print("\n".join(ids))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    data = load_manifest(Path(args.manifest))
    counts = {st: 0 for st in STATUSES}
    for s in data.get("slices", []):
        st = s.get("status")
        if st in counts:
            counts[st] += 1
    counts["total"] = len(data.get("slices", []))
    print(json.dumps(counts))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Slice manifest for resumable orchestrator runs.")
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init")
    pi.add_argument("--run-id", required=True)
    pi.add_argument("--head", default="")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add")
    pa.add_argument("--id", required=True)
    pa.add_argument("--title", required=True)
    pa.add_argument("--files", default="")
    pa.set_defaults(func=cmd_add)

    ps = sub.add_parser("set")
    ps.add_argument("--id", required=True)
    ps.add_argument("--status")
    ps.add_argument("--commit")
    ps.add_argument("--note")
    ps.set_defaults(func=cmd_set)

    pst = sub.add_parser("status")
    pst.add_argument("--id")
    pst.set_defaults(func=cmd_status)

    pn = sub.add_parser("next")
    pn.set_defaults(func=cmd_next)

    pr = sub.add_parser("resume")
    pr.set_defaults(func=cmd_resume)

    psu = sub.add_parser("summary")
    psu.set_defaults(func=cmd_summary)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
