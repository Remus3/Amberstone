"""gated_tft_live_keys.py - RM-292 (c) read-back: are three tft_live_data.json keys write-only?

RM-292 (c) (filed lane 8 cycle 34) says ``bench_units``, ``shop_units`` and
``unit_swap`` are written into ``data/tft_live_data.json`` by
``tft/tft_live_analysis.py`` ``TftLiveAnalysis._write`` and read back only off
in-memory dicts, never off the file - and asks for confirmation against a live
TFT game before the keys are deleted. That splits into two halves, and this
tool reads both in ONE command:

  - LIVE half: snapshots of the file the RUNNING writer produced. A write by
    the live analysis is told apart from a seed by the ``degraded`` key: only
    ``_write`` (``degraded`` False) and ``_publish_degraded`` (True) set it;
    the facade seed (``coaches/tft_coach.py`` ``_default_payloads``), the
    policy placeholder (``core/feature_policy.py`` ``_TFT_LIVE_DISABLED_PAYLOAD``)
    and the game-end reset never do. Per snapshot: kind, mtime, whether each of
    the three keys is present, and how many entries are filled (counts only,
    never the unit names). ``--samples N --interval S`` polls the file so one
    run covers several analysis cycles (about one write a minute in a game).
  - CENSUS half (static, the deciding half): every tracked non-test source file
    is scanned for the three key literals. Python is parsed (``ast``) and each
    hit is classed ``read`` (``.get("k")``, ``x["k"]`` load), ``write``
    (``x["k"] = ...``), ``dict_key`` (a dict display key - a seed or a payload
    literal), ``sequence`` (a tuple / list / set element - ambiguous, listed,
    never counted) or ``other``. JS / TS / HTML lines naming a key are ``read``
    candidates (``web/js/main.js`` takes the whole file off the WS /push relay,
    ``agents/agent2_backend/file_ingest.py``). The writer module and the
    upstream vision-reply producers are reported but not counted as readers:
    the row's own claim is that their reads are of the in-memory vision dict.

PREDICATE (stated in docs/LIVE_GAME_GATED_SYNC.md RM-292 (c) before any game):
  PASS iff the census finds 0 readers AND live writes (``degraded`` False,
  ``augment_select`` False, mtime at or after ``--since``) carrying all three
  keys and every key of the HEAD ``_write`` literal were seen in at least
  ``--need`` (3) distinct stage rounds. FAIL iff the census finds a reader (the
  row is refuted: do not delete) or a live write lacks one of the three keys
  (the running writer is not HEAD's; a degraded republish may lack them on HEAD
  and is never failed). Anything else (no file, only seeds, too few rounds) is
  INCOMPLETE.

READ-ONLY: it reads files and runs ``git ls-files``; it never writes, moves,
locks or deletes anything, and it never ticks a row - its output is the INPUT
to the four-part evidence contract, never the evidence by itself.

USAGE (from a worktree it reads the MAIN checkout's data/ file; the census
reads the tree the tool lives in)
    python tools/gated_tft_live_keys.py
    python tools/gated_tft_live_keys.py --since 2026-10-27T18:00 --samples 40 --interval 15 --json
Exit 0 = PASS, 1 = INCOMPLETE, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout  # noqa: E402

KEYS = ("bench_units", "shop_units", "unit_swap")
LIST_KEYS = ("bench_units", "shop_units")
LIVE_REL = Path("data") / "tft_live_data.json"
WRITER_REL = "tft/tft_live_analysis.py"
# Producers of the in-memory vision dict the writer reads (upstream of the
# file): the reply sanitizer and the prompts that name the reply's fields.
UPSTREAM_REL = frozenset({"tft/tft_vision_reader.py", "vision_server/_inference.py",
                          "core/vision_routing.py"})
NEED_WRITES = 3
_PY = (".py",)
_JS = (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".vue", ".html")
_KEY_RE = re.compile(r"\b(" + "|".join(KEYS) + r")\b")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# -- writer key set (HEAD) ---------------------------------------------------

def writer_keys(source: str) -> set[str]:
    """Keys the HEAD ``TftLiveAnalysis._write`` puts in its ``out`` payload.

    The constant keys of the ``out = {...}`` dict display plus every constant
    ``out["k"] = ...`` store in the method. Empty when the method is not found.
    """
    tree = ast.parse(source)
    keys: set[str] = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_write"):
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if (isinstance(tgt, ast.Name) and tgt.id == "out"
                                and isinstance(node.value, ast.Dict)):
                            keys.update(k.value for k in node.value.keys
                                        if isinstance(k, ast.Constant) and isinstance(k.value, str))
                        if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                                and tgt.value.id == "out" and isinstance(tgt.slice, ast.Constant)
                                and isinstance(tgt.slice.value, str)):
                            keys.add(tgt.slice.value)
    return keys


# -- live half ---------------------------------------------------------------

def classify(data: Any) -> str:
    """``live_write`` / ``live_degraded`` (the analysis wrote it) or ``seed``."""
    if not isinstance(data, dict):
        return "unreadable"
    if "degraded" not in data:
        return "seed"
    return "live_degraded" if data.get("degraded") is True else "live_write"


def _filled(value: Any, key: str) -> int | None:
    if key in LIST_KEYS:
        if not isinstance(value, list):
            return None
        return sum(1 for u in value if isinstance(u, str) and u.strip() and u != "empty")
    return len(value.strip()) if isinstance(value, str) else None


def snapshot(path: Path, head_keys: set[str]) -> dict[str, Any]:
    """One read of the live file: kind, mtime, key presence and fill counts."""
    try:
        st = path.stat()
    except OSError:
        return {"kind": "absent", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {"kind": "unreadable", "path": str(path), "mtime": st.st_mtime,
                "mtime_ns": st.st_mtime_ns}
    kind = classify(data)
    snap: dict[str, Any] = {"kind": kind, "path": str(path), "mtime": st.st_mtime,
                            "mtime_ns": st.st_mtime_ns, "mtime_iso": _iso(st.st_mtime)}
    if isinstance(data, dict):
        snap["mode"] = data.get("mode")
        snap["stage_round"] = data.get("stage_round")
        snap["keys_present"] = {k: k in data for k in KEYS}
        snap["filled"] = {k: _filled(data.get(k), k) for k in KEYS}
        snap["missing_head_keys"] = sorted(head_keys - set(data))
        snap["augment_select"] = data.get("augment_select") is True
    return snap


def collect(path: Path, head_keys: set[str], samples: int, interval: float,
            sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Poll the file ``samples`` times; one row per distinct file state."""
    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for i in range(max(1, samples)):
        if i:
            sleep(interval)
        snap = snapshot(path, head_keys)
        mark = (snap["kind"], snap.get("mtime_ns"))
        if mark not in seen:
            seen.add(mark)
            out.append(snap)
    return out


# -- census half -------------------------------------------------------------

def _py_hits(text: str) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [(n, k, "other") for n, line in enumerate(text.splitlines(), 1)
                for k in _KEY_RE.findall(line)]
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and node.value in KEYS):
            continue
        up = parent.get(id(node))
        role = "other"
        if isinstance(up, ast.Dict) and any(k is node for k in up.keys):
            role = "dict_key"
        elif (isinstance(up, ast.Call) and up.args and up.args[0] is node
              and isinstance(up.func, ast.Attribute)
              and up.func.attr in ("get", "pop", "setdefault")):
            role = "read"
        elif isinstance(up, ast.Subscript) and up.slice is node:
            role = "read" if isinstance(up.ctx, ast.Load) else "write"
        elif isinstance(up, (ast.Tuple, ast.List, ast.Set)):
            role = "sequence"
        elif isinstance(up, ast.Expr):
            continue  # a bare string statement (docstring) names, never reads
        hits.append((node.lineno, node.value, role))
    return hits


def _js_hits(text: str) -> list[tuple[int, str, str]]:
    return [(n, k, "read") for n, line in enumerate(text.splitlines(), 1)
            for k in _KEY_RE.findall(line)]


def is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return ("tests" in parts[:-1] or name.startswith("test_") or name == "conftest.py"
            or ".test." in name or name.endswith("_test.py"))


def is_scanned(rel: str) -> bool:
    """A Python / JS / TS / HTML source outside docs/ and outside the tests."""
    return rel.endswith(_PY + _JS) and not rel.startswith("docs/") and not is_test_path(rel)


def tracked_sources(root: Path) -> list[str]:
    """Tracked files under ``root`` (``git ls-files``) that ``is_scanned``."""
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=str(root), capture_output=True,
                          check=True, creationflags=_NO_WINDOW)
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    return sorted(n for n in names if is_scanned(n))


def census(root: Path, files: list[str] | None = None) -> dict[str, Any]:
    """Every key literal in ``files`` (default: ``tracked_sources(root)``), classed."""
    rels = tracked_sources(root) if files is None else sorted(files)
    hits: list[dict[str, Any]] = []
    for rel in rels:
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _KEY_RE.search(text):
            continue
        rows = _py_hits(text) if rel.endswith(_PY) else _js_hits(text)
        for line, key, role in rows:
            scope = ("writer" if rel == WRITER_REL else "upstream" if rel in UPSTREAM_REL
                     else "elsewhere")
            hits.append({"file": rel, "line": line, "key": key, "role": role, "scope": scope})
    readers = [h for h in hits if h["scope"] == "elsewhere" and h["role"] in ("read", "other")]
    return {"files_scanned": len(rels), "hits": hits, "readers": readers,
            "sequence": [h for h in hits if h["role"] == "sequence"],
            "writer_hits": sum(1 for h in hits if h["scope"] == "writer")}


# -- verdict -----------------------------------------------------------------

def verdict(snaps: list[dict[str, Any]], cen: dict[str, Any], need: int,
            since: float | None) -> tuple[str, str]:
    if cen["readers"]:
        r = cen["readers"][0]
        return "FAIL", (f"{len(cen['readers'])} reader(s) of the keys, first "
                        f"{r['file']}:{r['line']} {r['key']} ({r['role']}) - RM-292 (c) refuted")
    live = [s for s in snaps if s["kind"] in ("live_write", "live_degraded")
            and (since is None or s.get("mtime", 0) >= since)]
    # Only _write produces a live_write, and it always sets the three keys. A
    # live_degraded state may lack them on HEAD (_publish_degraded copies
    # whatever the file held), so it is reported, never failed.
    for s in (s for s in live if s["kind"] == "live_write"):
        absent = [k for k in KEYS if not s.get("keys_present", {}).get(k)]
        if absent:
            return "FAIL", (f"live write at {s.get('mtime_iso')} lacks {', '.join(absent)}: "
                            "the running writer is not HEAD's")
    # An augment-select merge or a force_scan pre-clear rewrites the previous
    # write in place (new mtime, degraded still false), so a write counts only
    # without augment_select, and the need is distinct stage rounds.
    full = [s for s in live if s["kind"] == "live_write" and not s.get("augment_select")
            and not s.get("missing_head_keys")]
    rounds = {s["stage_round"] for s in full
              if isinstance(s.get("stage_round"), str) and s["stage_round"].strip()}
    if len(rounds) >= need:
        return "PASS", (f"0 readers; {len(full)} live writes over {len(rounds)} stage rounds, "
                        f"every one carrying {', '.join(KEYS)}")
    return "INCOMPLETE", (f"{len(rounds)} of {need} stage rounds with a full live write"
                          + ("" if live else " (no live write seen: seed / absent only)"))


def report(root: Path, data_root: Path, samples: int, interval: float, need: int,
           since: float | None, sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    head = writer_keys((root / WRITER_REL).read_text(encoding="utf-8"))
    snaps = collect(data_root / LIVE_REL, head, samples, interval, sleep)
    cen = census(root)
    v, why = verdict(snaps, cen, need, since)
    # live_write only: a degraded republish carries the previous state's lists.
    live = [s for s in snaps if s["kind"] == "live_write"]
    populated = {k: sum(1 for s in live if (s.get("filled") or {}).get(k)) for k in KEYS}
    return {"verdict": v, "reason": why, "need": need, "since": _iso(since),
            "head_writer_keys": sorted(head), "snapshots": snaps,
            "live_writes": len(live),
            "degraded_states": sum(1 for s in snaps if s["kind"] == "live_degraded"),
            "populated_writes": populated, "census": cen,
            "data_root": str(data_root), "read_at": _iso(time.time())}


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _parse_since(text: str | None) -> float | None:
    if not text:
        return None
    return datetime.fromisoformat(text).timestamp()


def render(rep: dict[str, Any]) -> str:
    cen = rep["census"]
    lines = [f"RM-292 (c) verdict: {rep['verdict']} - {rep['reason']}",
             f"census: {cen['files_scanned']} files, {len(cen['hits'])} key hits, "
             f"{len(cen['readers'])} readers, {cen['writer_hits']} in the writer, "
             f"{len(cen['sequence'])} sequence (ambiguous)"]
    for h in cen["readers"] + cen["sequence"]:
        lines.append(f"  {h['role']:<8} {h['scope']:<9} {h['file']}:{h['line']} {h['key']}")
    lines.append(f"live file: {rep['data_root']} ({len(rep['snapshots'])} distinct states, "
                 f"{rep['live_writes']} live writes; populated {rep['populated_writes']})")
    for s in rep["snapshots"]:
        lines.append(f"  {s['kind']:<13} {s.get('mtime_iso')} stage {s.get('stage_round')!r} "
                     f"keys {s.get('keys_present')} filled {s.get('filled')}"
                     + (f" missing_head {s['missing_head_keys']}" if s.get("missing_head_keys") else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="ISO local time; live writes before it do not count")
    ap.add_argument("--samples", type=int, default=1, help="reads of the live file (default 1)")
    ap.add_argument("--interval", type=float, default=15.0, help="seconds between reads")
    ap.add_argument("--need", type=int, default=NEED_WRITES)
    ap.add_argument("--data-root", help="checkout whose data/ is read (default: main checkout)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    data_root = Path(a.data_root) if a.data_root else (main_checkout(_ROOT) or _ROOT)
    rep = report(_ROOT, data_root, a.samples, a.interval, a.need, _parse_since(a.since))
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "INCOMPLETE": 1}.get(rep["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
