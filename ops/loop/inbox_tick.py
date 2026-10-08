#!/usr/bin/env python
r"""RC's inbox, read on EVERY lane / loop fire (FLEET-KIT v8, FLEET-COMMON 14).

MAIN 2026-10-05 0310 ORDER (operator's standing order, relayed) and 0327 RULING.
The separate high-frequency responder (tools/inbox_responder_runner.py, the
RC-InboxResponder task) bypassed the kit's spawn helper, so the kit's
120-runs-per-24h cap could not count it, and it spent a hop budget of its own.
This module is the replacement: one cheap pass the lane launcher and the loop
controller run at the TOP of every fire, before any build work.

THE PASS (kit `fleet_inbox`, consumed, never edited):
  scan(root, inbox, "RC")         unseen notes, oldest mtime first (FLEET 7)
  SKIP  own / TERMINAL / no-reply  -> mark_seen, nothing else
  ACK   ACK-family / ANSWER / past the hop limit -> mark_seen: the mechanical
        ack is a ledger line, NEVER a note and never a spawn
  WORK  ORDER / FIX / RULING      -> a work row in ops/loop/control/
        inbox_work.jsonl (never triaged, never damped); a MAIN note is checked
        against MAIN's committed outbox copy (kit verify_main) and the row says
        main-verified / main-unverified, so an unverified "order" never carries
        MAIN's authority
  TRIAGE anything else            -> ONE kit spawn, kind="triage",
        fleet_inbox.TRIAGE_SPAWN (sonnet, effort low, bare); parse_verdict()
        gives NOREPLY / ACK / ANSWER and the note is marked seen either way
  ANSWER parts -> ONE batched note per destination (batch_note, HOP line), only
        when may_reply() holds, the sender is a counterparty, and
        OutboundCap(root).allow("ANSWER"); delivery is the pre-authorised
        channel-REPLY carve-out (CLAUDE.md halt boundary), re-hashed after the
        write. Anything not sent is HELD under ops/loop/control/inbox_held/.

BOUNDS, BECAUSE THIS RUNS INSIDE A FIRE. A triage spawn can take up to its kit
timeout (300 s). At most MAX_TRIAGE_PER_TICK (1) triage spawns run per fire;
further unclassifiable notes stay UNSEEN for the next fire. Free classification
has no bound - it is a file read. Two fires at once cannot both process one
note: the pass holds ops/loop/control/inbox_tick.lock (O_EXCL; a lock older
than LOCK_STALE_S is reclaimed), and a fire that finds it held skips the pass.

ARMING. Classification, acks and work rows are local ledger lines and always
run - the inbox may never wait for a human (0310 section 0). A SPAWN and an
outbound note need the ONE agreement record (0327 RULING): MAIN a counterparty
plus a MAIN outbox row for the sha256 check, every live participant in, no
retired code, an expiry, and NO hop budget of its own - the kit's 120 / 24 h
is the only budget. Without it triage is deferred (notes stay unseen) and the
summary says `armed: False`. ops/runtime/INBOX_RESPONDER_STOP is passed to the
kit as halt_file, so the existing responder stop flag still stops spawns.

THE OLD RECORD IS NOT READ HERE. tools/inbox_responder_runner.load_agreement
keeps its own (hop-budget) shape and refuses the v8 record (`malformed:
hop_budget`): that responder stays disarmed, which is the ruling's point.

NEVER FAILS A FIRE. `fire_step` swallows every fault into the summary's
`errors` and completes the checklist row; the lane still runs.

Stdlib only; importable as `ops.loop.inbox_tick` or by file path.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KIT = _HERE.parent / "fleet_kit"


def _bind_kit(name: str):
    try:
        return importlib.import_module(f"ops.fleet_kit.{name}")
    except ImportError:
        pass
    modname = f"rc_fleet_kit_{name}"
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# core/polled_json.py holds the repo's atomic-write contract (the ops/loop
# sibling-writer guard): plain import first, absolute-path bind as fallback.
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _pj_name = "rc_core_polled_json"
    if _pj_name in sys.modules:
        _atomic_write_bytes = sys.modules[_pj_name].atomic_write_bytes
    else:
        _pj_spec = importlib.util.spec_from_file_location(
            _pj_name, _HERE.parents[1] / "core" / "polled_json.py")
        _pj = importlib.util.module_from_spec(_pj_spec)
        sys.modules[_pj_name] = _pj
        _pj_spec.loader.exec_module(_pj)
        _atomic_write_bytes = _pj.atomic_write_bytes

fleet_inbox = _bind_kit("fleet_inbox")
fleet_headless = _bind_kit("fleet_headless")

CODE = "RC"
MAIN = "MAIN"
INBOX_DIR = "moon_sync_inbox"
CONFIG_REL = Path("ops/moon_sync_repos.json")
AGREEMENT_REL = Path("ops/runtime/inbox_responder_agreement.json")
AGREEMENT_SCHEMA = "rc-inbox-agreement-v8"
STOP_REL = Path("ops/runtime/INBOX_RESPONDER_STOP")
WORK_REL = Path("ops/loop/control/inbox_work.jsonl")
LOCK_REL = Path("ops/loop/control/inbox_tick.lock")
LAST_REL = Path("ops/loop/control/inbox_tick_last.json")
HELD_REL = Path("ops/loop/control/inbox_held")
DELIVERIES_REL = Path("ops/loop/control/inbox_deliveries.jsonl")
MAX_TRIAGE_PER_TICK = 1
LOCK_STALE_S = 900
STEP_ID = "I1"
STEP_TASK = "Read the RC inbox (scan, classify, triage)"
_UNSET = object()


# ---- small helpers ---------------------------------------------------------

def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _append(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="ascii", newline="\n") as fh:
        fh.write(json.dumps(doc) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(path, text.encode("ascii"))


def _parse_iso(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _naive(dt: datetime) -> datetime:
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt


# ---- configuration ---------------------------------------------------------

def load_roster(root) -> tuple[dict, set]:
    """(participants {code: inbox Path}, retired codes) from the gitignored
    per-host config. Absent / unreadable -> ({}, set()); codes never logged."""
    try:
        data = json.loads((Path(root) / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, set()
    if not isinstance(data, dict):
        return {}, set()
    parts = {}
    for code, base in (data.get("participants") or {}).items():
        if isinstance(code, str) and isinstance(base, str):
            parts[code] = Path(base) / INBOX_DIR
    retired = data.get("retired") or {}
    return parts, {str(c) for c in retired}


# ---- the agreement (MAIN 0327 RULING) ---------------------------------------

def validate_agreement(record, *, participants, retired, now) -> tuple:
    """(record, "") when the ONE v8 record arms the tick, else (None, detail).
    Fails closed on every field."""
    if not isinstance(record, dict):
        return None, "malformed:json"
    if record.get("schema") != AGREEMENT_SCHEMA:
        return None, "malformed:schema"
    if "hop_budget" in record:
        return None, "malformed:own_hop_budget (the kit's 120 / 24 h is the only budget)"
    if record.get("budget") != "kit":
        return None, "malformed:budget"
    parties = record.get("counterparties")
    if not isinstance(parties, list) or not all(isinstance(p, str) for p in parties):
        return None, "malformed:counterparties"
    if any(p in retired for p in parties):
        return None, "malformed:counterparties_retired"
    if MAIN not in parties:
        return None, "malformed:main_missing"
    if any(p not in participants and p != MAIN for p in parties):
        return None, "malformed:counterparties_unmapped"
    if any(p not in parties for p in participants):
        return None, "malformed:participant_missing"
    main = record.get("main")
    if not isinstance(main, dict) or main.get("code") != MAIN or \
            not isinstance(main.get("outbox"), str) or not main["outbox"].strip():
        return None, "malformed:main_outbox"
    expires = _parse_iso(record.get("expires"))
    if expires is None:
        return None, "malformed:expires"
    if _naive(now) >= _naive(expires):
        return None, "expired"
    return record, ""


def load_agreement(root, *, participants, retired, now) -> tuple:
    path = Path(root) / AGREEMENT_REL
    if not path.exists():
        return None, "no_agreement"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "malformed:json"
    return validate_agreement(record, participants=participants, retired=retired, now=now)


# ---- the lock --------------------------------------------------------------

def _take_lock(root: Path, clock=time.time) -> bool:
    lock = root / LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                ts = float(json.loads(lock.read_text(encoding="ascii")).get("ts", 0))
            except (OSError, ValueError, TypeError, AttributeError):
                try:
                    ts = lock.stat().st_mtime
                except OSError:
                    ts = 0.0
            if clock() - ts < LOCK_STALE_S:
                return False
            with contextlib.suppress(OSError):
                lock.unlink()
            continue
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "ts": clock()}))
        return True
    return False


def _drop_lock(root: Path) -> None:
    with contextlib.suppress(OSError):
        (root / LOCK_REL).unlink()


# ---- default seams ---------------------------------------------------------

def _default_verify(note, outbox) -> bool:
    return bool(fleet_headless.verify_main(note, outbox))


def _make_deliver(root: Path, participants: dict, agreement):
    """Write ONE reply into the destination inbox (atomic), re-hash it, and
    ledger the delivery. Returns the reached count (1 / 0)."""
    def deliver(to, fname, body):
        dest = participants.get(to)
        if dest is None and to == MAIN and agreement:
            inbox = (agreement.get("main") or {}).get("inbox")
            dest = Path(inbox) if isinstance(inbox, str) and inbox.strip() else None
        if dest is None or not Path(dest).is_dir():
            return 0
        data = body.encode("ascii")
        target = Path(dest) / fname
        _atomic_write_bytes(target, data)
        want = hashlib.sha256(data).hexdigest()
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        reached = 1 if got == want else 0
        _append(root / DELIVERIES_REL, {"ts": _iso_now(), "note": fname, "to": to,
                                        "sha256": want, "reached": f"{reached}/1"})
        return reached
    return deliver


# ---- the pass --------------------------------------------------------------

def _empty_summary(dry: bool) -> dict:
    return {"ts": _iso_now(), "unseen": 0, "skipped": 0, "acked": 0, "escalated": 0,
            "triaged": 0, "deferred": 0, "sent": 0, "held": 0, "armed": False,
            "agreement": "", "locked": False, "dry": bool(dry), "work": [],
            "errors": []}


def tick(root, *, inbox=None, code=CODE, agreement=_UNSET, participants=None,
         retired=None, spawn=None, spawn_kw=None, verify=None, deliver=None,
         now=None, dry=False, max_triage=MAX_TRIAGE_PER_TICK, emit=None) -> dict:
    """One inbox pass. Returns the summary dict; raises only on a seam fault
    (fire_step catches that). `dry` classifies and writes nothing."""
    root = Path(root)
    inbox = root / INBOX_DIR if inbox is None else Path(inbox)
    emit = emit or (lambda _s: None)
    now = datetime.now() if now is None else now
    if participants is None or retired is None:
        p, r = load_roster(root)
        participants = p if participants is None else participants
        retired = r if retired is None else retired
    if agreement is _UNSET:
        agreement, detail = load_agreement(root, participants=participants,
                                           retired=retired, now=now)
    elif agreement is not None:
        agreement, detail = validate_agreement(agreement, participants=participants,
                                               retired=retired, now=now)
    else:
        detail = "no_agreement"
    s = _empty_summary(dry)
    s["armed"], s["agreement"] = agreement is not None, detail

    if not dry and not _take_lock(root):
        s["locked"] = True
        return s
    try:
        rows = fleet_inbox.scan(root, inbox, code)
        s["unseen"] = len(rows)
        if dry:
            for path, d in rows:
                emit(f"inbox dry: {path.name} -> {d.action} ({d.reason})")
            return s
        _process(root, rows, s, code=code, agreement=agreement,
                 participants=participants, spawn=spawn, spawn_kw=spawn_kw or {},
                 verify=verify or _default_verify,
                 deliver=deliver or _make_deliver(root, participants, agreement),
                 max_triage=max_triage, emit=emit)
    finally:
        if not dry:
            _drop_lock(root)
    return s


def _process(root, rows, s, *, code, agreement, participants, spawn, spawn_kw,
             verify, deliver, max_triage, emit):
    counterparties = set((agreement or {}).get("counterparties") or ())
    answers: dict = {}
    triaged = 0
    for path, d in rows:
        name = path.name
        if d.action == fleet_inbox.SKIP:
            fleet_inbox.mark_seen(root, path, d)
            s["skipped"] += 1
        elif d.action == fleet_inbox.ACK:
            fleet_inbox.mark_seen(root, path, d)
            s["acked"] += 1
        elif d.action == fleet_inbox.WORK:
            if d.sender == MAIN:
                outbox = ((agreement or {}).get("main") or {}).get("outbox")
                ok = bool(outbox) and bool(verify(path, outbox))
                prov = "main-verified" if ok else "main-unverified"
            else:
                prov = "sibling"
            _append(root / WORK_REL, {"ts": _iso_now(), "note": name, "cls": d.cls,
                                      "sender": d.sender, "hop": d.hop,
                                      "provenance": prov, "state": "open"})
            fleet_inbox.mark_seen(root, path, d, verdict="ESCALATED")
            s["escalated"] += 1
            s["work"].append(name)
            emit(f"inbox: {d.cls} {name} escalated ({prov})")
        else:
            if agreement is None or triaged >= max_triage:
                s["deferred"] += 1
                continue
            try:
                body = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                s["errors"].append(f"{name}: unreadable ({type(exc).__name__})")
                s["deferred"] += 1
                continue
            kw = dict(fleet_inbox.TRIAGE_SPAWN)
            kw.update(spawn_kw)
            kw.setdefault("halt_file", str(root / STOP_REL))
            do_spawn = spawn or fleet_headless.spawn
            triaged += 1
            try:
                line = do_spawn(root, code, fleet_inbox.triage_prompt(name, body),
                                note=name, kind="triage", **kw)
            except fleet_headless.Refused as exc:
                s["errors"].append(f"{name}: triage refused: {exc}"[:200])
                s["deferred"] += 1
                continue
            verdict, text = fleet_inbox.parse_verdict((line or {}).get("result"))
            fleet_inbox.mark_seen(root, path, d, verdict=verdict)
            s["triaged"] += 1
            if verdict == "ANSWER":
                if d.sender in counterparties and d.sender != code and \
                        fleet_inbox.may_reply(d.cls, d.hop):
                    answers.setdefault(d.sender, []).append((name, text, d.hop))
                else:
                    _hold(root, f"{name}.answer.txt", text)
                    s["held"] += 1
    _send(root, answers, s, code=code, deliver=deliver, emit=emit)


def _hold(root: Path, fname: str, text: str) -> None:
    _atomic_text(root / HELD_REL / fname,
                 (text or "").encode("ascii", "replace").decode("ascii") + "\n")


def _send(root, answers, s, *, code, deliver, emit):
    cap = fleet_inbox.OutboundCap(root)
    for to, parts in sorted(answers.items()):
        pairs = [(n, t) for n, t, _h in parts]
        if not cap.allow("ANSWER"):
            for n, t in pairs:
                _hold(root, f"{n}.answer.txt", t)
            s["held"] += len(pairs)
            continue
        hop_n = fleet_inbox.next_hop(max(h for _n, _t, h in parts))
        fname, body, _names = fleet_inbox.batch_note(code, to, pairs, hop_n=hop_n)
        try:
            reached = deliver(to, fname, body)
        except (OSError, UnicodeError) as exc:
            s["errors"].append(f"deliver {to}: {type(exc).__name__}")
            reached = 0
        if reached:
            cap.record(fname, "ANSWER", to, parts=len(pairs))
            s["sent"] += 1
            emit(f"inbox: answered {len(pairs)} note(s) to {to} in {fname}")
        else:
            _hold(root, fname, body)
            s["held"] += len(pairs)


# ---- the fire's checklist step (FLEET-COMMON 13 d) --------------------------

def summary_line(s: dict) -> str:
    if s.get("locked"):
        return "inbox: pass held by another fire, skipped"
    bits = [f"inbox: {s.get('unseen', 0)} unseen"]
    for k in ("skipped", "acked", "escalated", "triaged", "deferred", "sent", "held"):
        if s.get(k):
            bits.append(f"{s[k]} {k}")
    if not s.get("armed"):
        bits.append("spawns disarmed")
    if s.get("dry"):
        bits.append("dry")
    if s.get("errors"):
        bits.append(f"{len(s['errors'])} error(s)")
    return ", ".join(bits)


def fire_step(prog, *, step_id=STEP_ID, root=None, tick=None, **kw) -> dict:
    """Run the pass as the fire's `step_id` checklist row. NEVER raises."""
    run = tick if tick is not None else globals()["tick"]
    root = Path(root) if root is not None else Path(prog.root)
    try:
        prog.set_state(step_id, "reading inbox", 30, step=f"{step_id} reading inbox")
    except Exception:  # noqa: BLE001 - progress never fails a fire
        pass
    try:
        s = run(root, **kw)
    except Exception as exc:  # noqa: BLE001 - the inbox pass never fails a fire
        s = _empty_summary(kw.get("dry", False))
        s["errors"].append(f"{type(exc).__name__}: {exc}"[:200])
    with contextlib.suppress(OSError, TypeError, ValueError):
        _atomic_text(root / LAST_REL, json.dumps(s, sort_keys=True) + "\n")
    try:
        prog.complete(step_id, step=f"{step_id} {summary_line(s)}")
    except Exception:  # noqa: BLE001
        pass
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One RC inbox pass (FLEET-COMMON 14).")
    ap.add_argument("--root", default=None, help="main checkout (default: this tree's)")
    ap.add_argument("--dry", action="store_true", help="classify only, write nothing")
    args = ap.parse_args(argv)
    if args.root:
        root = Path(args.root)
    else:
        root = _bind_kit("fleet_lanes").main_tree(_HERE.parents[1])
    s = tick(root, dry=args.dry, emit=print)
    if not args.dry:
        # Item F: the RC-InboxResponder task runs this CLI under pythonw (no
        # stdout), so the summary file is a scheduled fire's only read-back.
        with contextlib.suppress(OSError, TypeError, ValueError):
            _atomic_text(root / LAST_REL, json.dumps(s, sort_keys=True) + "\n")
    print(json.dumps(s, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
