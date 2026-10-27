"""gated_vision_pillow.py - which Pillow the RUNNING :8889 vision process holds.

The hand-off live read-back S6 asks whether vision decodes a live frame under
Pillow 13 (`cef8bfd22` moved the pin to 13.0.0). `tools/gated_frame_readback.py`
decodes the relay frame in THIS probe's interpreter, which is the SUBSTITUTION
trap for S6: it proves the bytes decode under the probe's Pillow, not that the
vision process loaded or used any Pillow at all. This tool reads the other half
from the vision process itself, without touching it:

1. The process listening on ``127.0.0.1:8889`` (pid, interpreter, start time).
2. Its MAPPED modules (``psutil.Process.memory_maps``): a mapped
   ``PIL\\_imaging*.pyd`` means Pillow is imported IN that process. Every
   ``from PIL import ...`` in ``vision_server/`` sits inside a function, so the
   module is absent until a capture, a decode, an OCR crop or a header-only
   read (``/upload-frame``, ``/vision``) runs. Loaded is not "decoded".
3. The ``pillow-*.dist-info`` beside that loaded ``PIL`` directory: its
   ``Version:`` line and its install time, compared with the process start.
4. The relay's ``/stats`` counters (``ocr``, ``vision``, ``frame_upload``,
   ``capture_skip``). They are CONTEXT, not decode evidence: ``_record`` counts
   every call, and a ``vision`` success can follow a header-only read or a
   swallowed ``Image.open`` failure. ``frame_upload.calls`` read AFTER the frame
   read-back is a lifetime count. ``stats_tie`` says whether the reply came from
   the pinned process: the listener is re-read AFTER the GET (same pid and
   ``create_time``) and ``uptime_s`` must match ``create_time``. With both true,
   the same pid read before the read-back, and a ``create_time`` older than the
   frame's ``ts``, 0 rules out an ``/upload-frame`` frame (which carries a
   caller-chosen ``source``); non-zero means it cannot be ruled out.

READ-ONLY: no write, no signal, no restart; one GET to ``/stats`` (token from
``gated_frame_readback.resolve_token``, never printed). It never ticks a row.

USAGE
    python tools/gated_vision_pillow.py           # text to stdout
    python tools/gated_vision_pillow.py --json    # machine-readable

Exit 0 = the listener was read; 1 = nothing listens on :8889; 2 = no single
readable listener (psutil missing, access denied, or several pids listening).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

_PORT = 8889
_STATS_URL = "http://127.0.0.1:8889/stats"
_WANT = "13.0.0"
_IMAGING = re.compile(r"[\\/]PIL[\\/]_imaging(\.[^\\/]*)?\.pyd$", re.IGNORECASE)
_STAT_KEYS = ("ocr", "vision", "frame_upload")
# Measured 2026-10-27 at idle: wall - uptime_s - create_time = 0.53 s (the int
# floor plus the import time before ``_START_TIME``); 3 s leaves slack for a
# slow import and still refuses a successor started seconds later.
_UPTIME_TOL_S = 3.0


def loaded_pil_dir(mapped_paths) -> Path | None:
    """The ``PIL`` directory whose ``_imaging`` extension is mapped, else None."""
    for path in mapped_paths:
        if isinstance(path, str) and _IMAGING.search(path):
            return Path(path).parent
    return None


def dist_facts(site_dir: Path) -> list[dict]:
    """Every ``pillow-*.dist-info`` in ``site_dir``: version and METADATA mtime."""
    out = []
    try:
        entries = sorted(site_dir.iterdir())
    except OSError:
        return out
    for entry in entries:
        name = entry.name.lower()
        if not (name.startswith("pillow-") and name.endswith(".dist-info")):
            continue
        meta = entry / "METADATA"
        version = None
        try:
            for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                    break
            mtime = meta.stat().st_mtime
        except OSError:
            mtime = None
        out.append({"dist_info": entry.name, "version": version,
                    "installed_ts": mtime})
    return out


def s6_checks(report: dict, want: str = _WANT) -> dict:
    """The S6 process-side predicate parts, each True / False / None (unknown)."""
    dists = report.get("dists") or []
    start = report.get("create_time")
    loaded = report.get("pil_loaded")
    one = len(dists) == 1
    version_ok = (dists[0].get("version") == want) if one else (False if dists else None)
    ts = dists[0].get("installed_ts") if one else None
    before = (ts < start) if (isinstance(ts, (int, float))
                              and isinstance(start, (int, float))) else None
    return {"pil_loaded_in_process": loaded,
            "single_pillow_dist": one if dists else None,
            "version_is_" + want: version_ok,
            "installed_before_process_start": before}


def find_listeners(conns, port: int = _PORT) -> list:
    """Sorted distinct pids holding a LISTEN socket on ``port`` in ``conns``."""
    pids = set()
    for c in conns:
        laddr = getattr(c, "laddr", None)
        if laddr and getattr(laddr, "port", None) == port and c.status == "LISTEN":
            pids.add(c.pid)
    return sorted(p for p in pids if p is not None)


def find_listener(conns, port: int = _PORT):
    """The single listener pid on ``port``; None when there is none or several."""
    pids = find_listeners(conns, port)
    return pids[0] if len(pids) == 1 else None


def stats_tie(report: dict, again: dict, wall: float, uptime_s,
              tolerance_s: float = _UPTIME_TOL_S) -> dict:
    """Whether the ``/stats`` reply came from the pinned process.

    ``again`` is the listener re-read AFTER the GET: a different pid or
    ``create_time`` means the port changed hands around the GET. ``uptime_s``
    (an int of ``time.time() - _START_TIME``, set at import) must also put that
    process's start within ``tolerance_s`` of the pinned ``create_time``.
    """
    same = (again.get("pid") == report.get("pid")
            and again.get("create_time") == report.get("create_time")
            and report.get("pid") is not None)
    start = report.get("create_time")
    if isinstance(uptime_s, (int, float)) and isinstance(start, (int, float)):
        uptime_ok = abs(wall - uptime_s - start) <= tolerance_s
    else:
        uptime_ok = None
    return {"same_process_after_get": same, "uptime_matches_create_time": uptime_ok}


def stats_counters(body: dict) -> dict:
    """``/stats`` reduced to the decode counters and the capture skips."""
    stats = body.get("stats") if isinstance(body, dict) else None
    stats = stats if isinstance(stats, dict) else {}
    out = {}
    for key in _STAT_KEYS:
        row = stats.get(key)
        if isinstance(row, dict):
            out[key] = {"calls": row.get("calls"), "errors": row.get("errors")}
    skip = body.get("capture_skip") if isinstance(body, dict) else None
    if isinstance(skip, dict):
        out["capture_skip"] = {k: skip.get(k) for k in
                               ("not_foreground", "blank", "locked", "last_reason")}
    if isinstance(body, dict) and "uptime_s" in body:
        out["uptime_s"] = body["uptime_s"]
    return out


def _fetch_stats(url: str = _STATS_URL) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gated_frame_readback as fr  # noqa: PLC0415 - sibling tool, lazy
    token, source = fr.resolve_token()
    if not token:
        return {"error": "no vision token", "token_source": source}
    req = urllib.request.Request(url, headers={"X-RC-Token": token})
    try:
        with fr._OPENER.open(req, timeout=5.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - any failure is the answer
        return {"error": f"{type(exc).__name__}", "token_source": source}
    out = stats_counters(body)
    out["token_source"] = source
    return out


def read_process(psutil_mod=None, port: int = _PORT) -> tuple[int, dict]:
    """Read the listener's facts; ``(exit_code, report)``."""
    if psutil_mod is None:
        try:
            import psutil as psutil_mod  # noqa: PLC0415
        except ImportError:
            return 2, {"error": "psutil not installed"}
    try:
        pids = find_listeners(psutil_mod.net_connections("tcp"), port)
    except Exception as exc:  # noqa: BLE001
        return 2, {"error": f"net_connections: {type(exc).__name__}"}
    if not pids:
        return 1, {"error": f"nothing listens on :{port}"}
    if len(pids) > 1:
        return 2, {"error": f"{len(pids)} processes listen on :{port}",
                   "listener_pids": pids}
    pid = pids[0]
    report: dict = {"pid": pid}
    try:
        proc = psutil_mod.Process(pid)
        report["exe"] = proc.exe()
        report["create_time"] = proc.create_time()
        mapped = [m.path for m in proc.memory_maps()]
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"process read: {type(exc).__name__}"
        return 2, report
    pil_dir = loaded_pil_dir(mapped)
    report["pil_loaded"] = pil_dir is not None
    report["pil_dir"] = str(pil_dir) if pil_dir else None
    report["dists"] = dist_facts(pil_dir.parent) if pil_dir else []
    report["s6"] = s6_checks(report)
    return 0, report


def _render(report: dict) -> str:
    lines = []
    for key in ("pid", "exe", "create_time", "pil_loaded", "pil_dir", "error"):
        if key in report:
            lines.append(f"{key}: {report[key]}")
    for d in report.get("dists") or []:
        lines.append(f"dist: {d['dist_info']} version {d['version']} "
                     f"installed_ts {d['installed_ts']}")
    for k, v in (report.get("s6") or {}).items():
        lines.append(f"s6.{k}: {v}")
    for k, v in (report.get("stats") or {}).items():
        lines.append(f"stats.{k}: {v}")
    for k, v in (report.get("stats_tie") or {}).items():
        lines.append(f"stats_tie.{k}: {v}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-stats", action="store_true",
                    help="skip the one /stats GET")
    args = ap.parse_args(argv)
    code, report = read_process()
    if code == 0 and not args.no_stats:
        wall = time.time()
        report["stats"] = _fetch_stats()
        _code, again = read_process()
        report["stats_tie"] = stats_tie(report, again, wall,
                                        report["stats"].get("uptime_s"))
    print(json.dumps(report, indent=2, sort_keys=True) if args.json
          else _render(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
