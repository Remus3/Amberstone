# arch: data layer for the three ops dashboard panels | section=core | frozen=no
"""Backing data for ADDENDUM A concepts 3, 4 and 5.

Three read-only computations, no new state and no engine math:

- ``compute_seam_map``    - DS route seams against the THREE gates.
- ``compute_drift_strip`` - one freshness pill per fact that has burned a session.
- ``compute_gated_queue`` - the live-gated checklist as a per-mode countdown.

**Why the seam map re-derives instead of importing.** The authoritative scan
lives in ``agents/daemon_slayer/tests/test_stranded_hsp_seam_r197.py``, and a
dashboard route must not import from a test module - the test tree is not on
the serving path and pytest collection side effects have no business inside a
request. So the AST scan is reimplemented here against the same source file,
and ``tests/test_ops_panels.py`` cross-checks this module's output against that
ledger. Two independent derivations that must agree is the point; a shared
import would make agreement vacuous.

**The three gates, and why all three are needed.** A seam can be settable,
guard-green and arithmetically INERT - the failure
``reference_ds_route_seam_transport_vs_flag`` records. Flag alone says nothing:

    flag       the engine offers the parameter at all
    transport  server.py PARSES the key out of the request body
    route      server.py FORWARDS it as a kwarg to the engine call

R194 measured a parse-side drop, a key read and then never forwarded, which
made a live re-rank read as inert. That is why transport and route are separate
columns rather than one "wired" boolean.

Everything here fails soft: a missing file yields ``ok: False`` with a reason,
never an exception into the request path.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DS_SERVER = ROOT / "agents" / "daemon_slayer" / "server.py"
DS_LEDGER = (ROOT / "agents" / "daemon_slayer" / "tests"
             / "test_stranded_hsp_seam_r197.py")
DS_PATCH_FILE = ROOT / "data" / "daemon_slayer" / "current.txt"
DS_INIT = ROOT / "agents" / "daemon_slayer" / "__init__.py"
GATED_DOC = ROOT / "docs" / "LIVE_GAME_GATED_SYNC.md"


# ---------------------------------------------------------------------------
# 3. Seam map
# ---------------------------------------------------------------------------

def _parsed_keys(src: str) -> set[str]:
    """Seam names ``server.py`` reads out of a request body via ``_opt_bool``."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    return {
        n.args[1].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_opt_bool"
        and len(n.args) >= 2
        and isinstance(n.args[1], ast.Constant)
        and isinstance(n.args[1].value, str)
    }


def _passed_kwargs(src: str) -> set[str]:
    """Keyword-argument names ``server.py`` forwards on any call."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    return {
        kw.arg
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        for kw in n.keywords
        if kw.arg
    }


def _parse_stranded_ledger(src: str) -> dict[str, str]:
    """The ``STRANDED_TODAY`` name -> reason mapping, read as data.

    Parsed with ``ast`` rather than regex so a reason string containing a brace
    or a quote cannot desynchronise the scan.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    for node in ast.walk(tree):
        targets = getattr(node, "targets", None) or (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "STRANDED_TODAY":
                val = node.value
                if isinstance(val, ast.Dict):
                    out = {}
                    for k, v in zip(val.keys, val.values):
                        if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                                and isinstance(v, ast.Constant)):
                            out[k.value] = str(v.value)
                    return out
    return {}


def compute_seam_map() -> dict:
    """Every known DS seam against the three gates."""
    if not DS_SERVER.exists():
        return {"ok": False, "reason": "ds server source not found",
                "seams": [], "inert_count": 0}

    src = DS_SERVER.read_text(encoding="utf-8", errors="replace")
    parsed, passed = _parsed_keys(src), _passed_kwargs(src)
    ledger = _parse_stranded_ledger(
        DS_LEDGER.read_text(encoding="utf-8", errors="replace")
        if DS_LEDGER.exists() else "")

    rows = []
    for name in sorted(parsed | set(ledger)):
        transport = "yes" if name in parsed else "no"
        route = "yes" if name in passed else "no"
        # Flag is "yes" for anything the engine exposes; a ledger entry is by
        # definition an engine seam, and a parsed key is one server.py knows.
        row = {
            "seam": name,
            "flag": "yes",
            "transport": transport,
            "route": route,
            "inert": transport == "no" or route == "no",
            "reason": ledger.get(name, ""),
        }
        rows.append(row)

    return {
        "ok": True,
        "seams": rows,
        "inert_count": sum(1 for r in rows if r["inert"]),
        "wired_count": sum(1 for r in rows if not r["inert"]),
    }


# ---------------------------------------------------------------------------
# 4. Drift strip
# ---------------------------------------------------------------------------

def _agreement_state(values: list[str]) -> str:
    """``ok`` when every non-empty value agrees, ``amber`` when they differ."""
    seen = {v for v in values if v}
    if not seen:
        return "unknown"
    return "ok" if len(seen) == 1 else "amber"


def _engine_version(path: Path) -> str:
    if not path.exists():
        return ""
    m = re.search(r'ENGINE_VERSION\s*=\s*"([^"]+)"',
                  path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else ""


def compute_drift_strip() -> dict:
    """One pill per freshness fact, amber the moment two sources disagree."""
    pills: list[dict] = []

    ds_patch = (DS_PATCH_FILE.read_text(encoding="utf-8").strip()
                if DS_PATCH_FILE.exists() else "")
    pills.append({
        "key": "ds_patch", "label": "DS patch", "value": ds_patch or "-",
        "state": "ok" if ds_patch else "unknown",
        "reason": "" if ds_patch else "data/daemon_slayer/current.txt missing",
    })

    engine = _engine_version(DS_INIT)
    pills.append({
        "key": "engine", "label": "ENGINE", "value": engine or "-",
        "state": "ok" if engine else "unknown",
        "reason": "" if engine else "ENGINE_VERSION not found",
    })

    # Patch-keyed data directories: the newest one should be the live patch.
    data_dir = ROOT / "data" / "daemon_slayer"
    patch_dirs = sorted(
        (p.name for p in data_dir.iterdir()
         if p.is_dir() and re.fullmatch(r"\d+\.\d+\.\d+", p.name)),
        key=lambda s: [int(x) for x in s.split(".")],
    ) if data_dir.exists() else []
    newest = patch_dirs[-1] if patch_dirs else ""
    dir_state = _agreement_state([ds_patch, newest])
    pills.append({
        "key": "patch_data", "label": "patch data", "value": newest or "-",
        "state": dir_state,
        "reason": ("" if dir_state == "ok"
                   else f"newest data dir {newest or '-'} against patch {ds_patch or '-'}"),
    })

    return {
        "ok": True,
        "pills": pills,
        "amber_count": sum(1 for p in pills if p["state"] != "ok"),
    }


# ---------------------------------------------------------------------------
# 5. Gated queue
# ---------------------------------------------------------------------------

_GATE_RE = re.compile(r"^##\s+GATE\s+(\d+)\s*-\s*(.+?)\s*$", re.M)

# Rows are `- **G2-01** ...`, NOT markdown checkboxes. Measured 2026-08-01:
# the doc carries 135 of these and ZERO `- [ ]` items, so a checkbox regex
# matches nothing and every count reconciles at 0 - which reads exactly like
# "no open work" instead of "the parser is broken".
_ROW_RE = re.compile(r"^\s*-\s+\*\*(G\d+-\d+)\*\*")

# A row is closed only on an EXPLICIT marker. Defaulting to open is deliberate:
# under-reporting remaining work is the expensive direction of this error.
_DONE_RE = re.compile(
    r"\b(EYEBALL DONE|DONE \d{4}-\d{2}-\d{2}|NO LIVE RESIDUAL|CLOSED|REFUTED|STRUCK)\b")


def compute_gated_queue(path: Path | None = None) -> dict:
    """The live-gated checklist as a per-mode countdown.

    Buckets come from the document's own ``## GATE n - NAME`` headings, so a
    new gate appears without a code change. Rows are checklist items inside
    each bucket; an unchecked box is open work.
    """
    doc = path or GATED_DOC
    if not doc.exists():
        return {"ok": False, "reason": f"{doc.name} not found",
                "buckets": [], "total_open": 0}

    text = doc.read_text(encoding="utf-8", errors="replace")
    heads = list(_GATE_RE.finditer(text))
    if not heads:
        return {"ok": False, "reason": "no '## GATE n - ' headings found",
                "buckets": [], "total_open": 0}

    buckets = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[start:end]
        open_n = done_n = 0
        lines = body.splitlines()
        for idx, line in enumerate(lines):
            if not _ROW_RE.match(line):
                continue
            # A row's prose continues on following indented lines, and the DONE
            # marker frequently sits there rather than on the bullet itself.
            blob = [line]
            for cont in lines[idx + 1:]:
                if _ROW_RE.match(cont) or cont.startswith(("#", "- **")):
                    break
                if not cont.strip():
                    break
                blob.append(cont)
            if _DONE_RE.search(" ".join(blob)):
                done_n += 1
            else:
                open_n += 1
        label = m.group(2)
        buckets.append({
            "gate": int(m.group(1)),
            "label": label,
            "mode": _mode_for(label),
            "open": open_n,
            "done": done_n,
        })

    return {
        "ok": True,
        "buckets": buckets,
        "total_open": sum(b["open"] for b in buckets),
        "total_done": sum(b["done"] for b in buckets),
    }


def _mode_for(label: str) -> str:
    """Short mode token for the panel's left column."""
    up = label.upper()
    if "ARAM" in up:
        return "ARAM"
    if "ARENA" in up:
        return "ARENA"
    if "PRACTICE" in up:
        return "PRACTICE"
    if "CHAMP-SELECT" in up or "LOBBY" in up:
        return "CHAMP-SEL"
    if "SR" in up:
        return "SR"
    return "ANY"
