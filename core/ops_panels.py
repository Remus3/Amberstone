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

A fourth, later card (Y-08, external reference M) lives at the bottom:
``compute_ingest_freshness`` - did the last game reach the rewind DB. It is
read-only like the others and opens sqlite in ``mode=ro`` only.
"""
from __future__ import annotations

import ast
import json
import math
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# 6. Match-ingest freshness (Y-08, external reference M - behaviour only)
# ---------------------------------------------------------------------------
#
# Sources, all read-only:
#   receipts   ops/runtime/rewind_ingest_receipts.jsonl  (lib/ingest_receipt.py,
#              one row per live-writer chain END)
#   catchup    data/rewind_catchup.state.json last_run_outcome / last_run_at
#              (scripts/rewind_catchup.py record_run)
#   backlog    fetch_retry by kind (scripts/rewind_catchup.py
#              pending_retry_counts - its first consumer outside the script)
#   lag        the last LCU EOG gameId (ops/runtime/last_game_end.json, the
#              Y-01 pin) against data/rewind_history.db
#
# The card has a FIXED row list (``INGEST_ROW_KEYS``): a fresh tree renders
# the same rows as a busy one, each with an explicit "none yet" value, so the
# page never reflows on data arriving. The pin file carries the live Riot ID;
# nothing from it but the game id, queue and mode is read into the payload.

INGEST_ROW_KEYS = ("last_receipt", "tally", "lag", "catchup", "retry_backlog")
INGEST_TALLY_WINDOW = 50

_CATCHUP_OK = frozenset({"hydrated", "no_new_matches", "retry_only"})
_CATCHUP_AMBER = frozenset({"pagination_rate_limited"})
_CATCHUP_RED = frozenset({"api_failure", "no_api_key"})


def _fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    s = max(0, int(seconds))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h {s % 3600 // 60}m"
    return f"{s // 86400}d"


def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _ro_conn(db_path: Path) -> sqlite3.Connection | None:
    """mode=ro connection, or None when the DB is absent. Never creates it."""
    if not db_path.is_file():
        return None
    return sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True,
                           timeout=2.0)


def _read_pin(pin_path: Path) -> dict | None:
    """Game id / queue / mode / time from the Y-01 pin. Riot ID never read out."""
    try:
        data = json.loads(pin_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    gid = str(data.get("game_id") or "").strip()
    if not gid.isdigit() or not gid.isascii():
        return None
    qid = data.get("queue_id")
    return {
        "game_id": gid,
        "queue_id": qid if isinstance(qid, int) and not isinstance(qid, bool) else None,
        "game_mode": str(data.get("game_mode") or "").strip().upper()[:16],
        "written_at": _num(data.get("written_at")),
    }


def _ingest_lag(pin_path: Path, db_path: Path, now: float) -> dict:
    out: dict[str, Any] = {"state": "no_pin", "last_eog_target": None,
                           "newest_match_id": None, "newest_end_ts": None,
                           "behind_s": None, "reason": ""}
    pin = _read_pin(pin_path)
    try:
        conn = _ro_conn(db_path)
    except sqlite3.Error as exc:
        conn = None
        out["reason"] = f"rewind DB unreadable ({type(exc).__name__})"
    newest = None
    present = None
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT match_id, COALESCE(game_end_ts, game_creation_ts) "
                "FROM matches ORDER BY COALESCE(game_end_ts, game_creation_ts) "
                "DESC LIMIT 1").fetchone()
            newest = row
            if pin is not None:
                from core import operator_identity
                target = f"{operator_identity.platform()}_{pin['game_id']}"
                out["last_eog_target"] = target
                present = conn.execute(
                    "SELECT 1 FROM matches WHERE match_id=?",
                    (target,)).fetchone() is not None
        except sqlite3.Error as exc:
            out["reason"] = f"rewind DB unreadable ({type(exc).__name__})"
            present = None
        finally:
            conn.close()
    if newest:
        out["newest_match_id"] = newest[0]
        out["newest_end_ts"] = _num(newest[1])
    if pin is None:
        return out
    if out["last_eog_target"] is None:
        from core import operator_identity
        out["last_eog_target"] = f"{operator_identity.platform()}_{pin['game_id']}"
    from lib import rewind_live_writer as rlw
    if (pin["queue_id"] in rlw.EVENT_MODE_QUEUE_IDS
            or pin["game_mode"] in rlw.EVENT_MODE_GAME_MODES):
        out["state"] = "excluded"
        return out
    if present is None:
        out["state"] = "unknown"
        out["reason"] = out["reason"] or "rewind DB not found"
        return out
    if present:
        out["state"] = "caught_up"
        return out
    out["state"] = "behind"
    if pin["written_at"] is not None:
        out["behind_s"] = round(max(0.0, now - pin["written_at"]), 3)
    return out


def _catchup_state(state_path: Path) -> dict:
    out: dict[str, Any] = {"state": "missing", "last_run_outcome": None,
                           "last_run_at": None, "last_run_rc": None}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except OSError:
        return out
    except ValueError:
        out["state"] = "unreadable"
        return out
    if not isinstance(data, dict):
        out["state"] = "unreadable"
        return out
    at = data.get("last_run_at")
    out["last_run_at"] = at if isinstance(at, str) else None
    outcome = data.get("last_run_outcome")
    rc = data.get("last_run_rc")
    out["last_run_rc"] = rc if isinstance(rc, int) and not isinstance(rc, bool) else None
    if isinstance(outcome, str) and outcome:
        out["last_run_outcome"] = outcome
        out["state"] = "known"
    else:
        # A run before record_run existed: it ran, but said nothing about how.
        out["state"] = "unrecorded"
    return out


def _retry_backlog(db_path: Path) -> dict:
    out: dict[str, Any] = {"readable": False, "by_kind": {}, "total": 0,
                           "reason": ""}
    if not db_path.is_file():
        out["readable"] = True          # no DB = no queue, by the script's rule
        out["reason"] = "rewind DB not found"
        return out
    try:
        from scripts import rewind_catchup
        counts = rewind_catchup.pending_retry_counts(db_path)
    except Exception as exc:  # noqa: BLE001 - one bad source degrades one row
        out["reason"] = f"fetch_retry unreadable ({type(exc).__name__})"
        return out
    by_kind = {str(k): int(v) for k, v in sorted(counts.items())}
    out.update(readable=True, by_kind=by_kind, total=sum(by_kind.values()))
    return out


def _receipt_state(cls: str) -> str:
    from lib import ingest_receipt as ir
    if cls in (ir.CLASS_INGESTED, ir.CLASS_EXCLUDED):
        return "ok"
    if cls == ir.CLASS_DEFERRED:
        return "amber"
    return "red"                         # failed AND unknown


def compute_ingest_freshness(
    *,
    receipt_path: Path | None = None,
    state_path: Path | None = None,
    db_path: Path | None = None,
    pin_path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Did the last game reach the rewind DB? Read-only; never raises."""
    from lib import ingest_receipt as ir
    from lib import rewind_live_writer as rlw

    rp = Path(receipt_path) if receipt_path is not None else ir.RECEIPT_PATH
    sp = (Path(state_path) if state_path is not None
          else ROOT / "data" / "rewind_catchup.state.json")
    dp = Path(db_path) if db_path is not None else rlw.DB_PATH
    pp = Path(pin_path) if pin_path is not None else rlw.PIN_PATH
    t_now = _num(now)
    if t_now is None:
        t_now = time.time()

    receipts = ir.read_receipts(rp, limit=INGEST_TALLY_WINDOW)

    by_status: dict[str, int] = {}
    by_class = {c: 0 for c in (ir.CLASS_INGESTED, ir.CLASS_EXCLUDED,
                               ir.CLASS_DEFERRED, ir.CLASS_FAILED,
                               ir.CLASS_UNKNOWN)}
    for r in receipts:
        st = r["status"]
        by_status[st] = by_status.get(st, 0) + 1
        by_class[ir.classify(st)] += 1
    tally = {"rows": len(receipts), "window": INGEST_TALLY_WINDOW,
             "success": by_class[ir.CLASS_INGESTED],
             "by_status": dict(sorted(by_status.items())),
             "by_class": by_class}

    last = None
    if receipts:
        r = receipts[-1]
        ts = _num(r.get("ts"))
        target = r.get("target")
        last = {
            "target": target if isinstance(target, str) else None,
            "status": r["status"],
            "class": ir.classify(r["status"]),
            "success": ir.is_success(r["status"]),
            "attempts": r.get("attempts") if isinstance(r.get("attempts"), int) else None,
            "elapsed_s": _num(r.get("elapsed_s")),
            "parked": r.get("parked") is True,
            "ts": ts,
            "age_s": (round(max(0.0, t_now - ts), 3) if ts is not None else None),
        }

    lag = _ingest_lag(pp, dp, t_now)
    catchup = _catchup_state(sp)
    backlog = _retry_backlog(dp)

    if last is None:
        basis = ("no receipt yet - no live-writer chain has ended since "
                 "receipts began")
    else:
        basis = (f"last {tally['rows']} receipt(s); newest "
                 f"{_fmt_age(last['age_s'])} ago")

    rows = _ingest_rows(last, tally, lag, catchup, backlog)
    return {"ok": True, "basis": basis, "last_receipt": last, "tally": tally,
            "lag": lag, "catchup": catchup, "retry_backlog": backlog,
            "rows": rows}


def _ingest_rows(last, tally, lag, catchup, backlog) -> list[dict]:
    """The fixed row list the card renders, in ``INGEST_ROW_KEYS`` order."""
    rows: dict[str, dict] = {}

    if last is None:
        rows["last_receipt"] = ("Last game ingest", "no receipt yet", "unknown")
    else:
        bits = [last["target"] or "no target", last["status"]]
        if last["attempts"] is not None:
            bits.append(f"{last['attempts']} attempt(s)")
        if last["elapsed_s"] is not None:
            bits.append(f"{_fmt_age(last['elapsed_s'])} after game end")
        if last["parked"]:
            bits.append("parked for catchup")
        rows["last_receipt"] = ("Last game ingest", ", ".join(bits),
                                _receipt_state(last["class"]))

    if tally["rows"] == 0:
        rows["tally"] = ("Recent receipts", "none yet", "unknown")
    else:
        detail = ", ".join(f"{k} {v}" for k, v in tally["by_status"].items())
        good = tally["success"] + tally["by_class"]["excluded"]
        rows["tally"] = (
            "Recent receipts",
            f"{tally['success']} of {tally['rows']} ingested ({detail})",
            "ok" if good == tally["rows"] else "amber")

    st = lag["state"]
    if st == "no_pin":
        rows["lag"] = ("Last game vs rewind DB", "no game end recorded yet",
                       "unknown")
    elif st == "excluded":
        rows["lag"] = ("Last game vs rewind DB",
                       f"{lag['last_eog_target']} is an event mode Match-V5 "
                       "never serves", "ok")
    elif st == "caught_up":
        rows["lag"] = ("Last game vs rewind DB",
                       f"caught up - {lag['last_eog_target']} is in the DB", "ok")
    elif st == "behind":
        age = (f" for {_fmt_age(lag['behind_s'])}"
               if lag["behind_s"] is not None else "")
        rows["lag"] = ("Last game vs rewind DB",
                       f"behind{age} - {lag['last_eog_target']} not in the DB; "
                       f"newest {lag['newest_match_id'] or 'none'}", "amber")
    else:
        rows["lag"] = ("Last game vs rewind DB",
                       f"unknown - {lag['reason'] or 'rewind DB unreadable'}",
                       "unknown")

    cs = catchup["state"]
    when = catchup["last_run_at"] or "time unknown"
    if cs == "known":
        oc = catchup["last_run_outcome"]
        state = ("ok" if oc in _CATCHUP_OK else "amber" if oc in _CATCHUP_AMBER
                 else "red" if oc in _CATCHUP_RED else "unknown")
        rows["catchup"] = ("Catchup last run", f"{oc} at {when}", state)
    elif cs == "unrecorded":
        rows["catchup"] = ("Catchup last run",
                           f"outcome not recorded (ran {when})", "unknown")
    elif cs == "unreadable":
        rows["catchup"] = ("Catchup last run", "state file unreadable", "unknown")
    else:
        rows["catchup"] = ("Catchup last run", "never ran on this tree", "unknown")

    if not backlog["readable"]:
        rows["retry_backlog"] = ("fetch_retry backlog",
                                 backlog["reason"] or "unreadable", "unknown")
    elif backlog["total"] == 0:
        rows["retry_backlog"] = ("fetch_retry backlog", "0 pending", "ok")
    else:
        kinds = ", ".join(f"{k} {v}" for k, v in backlog["by_kind"].items())
        rows["retry_backlog"] = ("fetch_retry backlog",
                                 f"{backlog['total']} pending ({kinds})", "amber")

    return [{"key": k, "label": rows[k][0], "value": rows[k][1],
             "state": rows[k][2]} for k in INGEST_ROW_KEYS]
