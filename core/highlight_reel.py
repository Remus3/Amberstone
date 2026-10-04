"""RM-639 (directive X-39): death reel / highlight clips (ADR-016 "Clips").

Behaviour observed in external references G, H and E; re-implemented
clean-room from the directive's behaviour text. Nothing is vendored: ffmpeg is
an EXTERNAL binary the operator installs, located via config or PATH, never
bundled and never downloaded. NOTICE delta zero.

Two halves:

PURE (no IO): the RM-637 recorder sidecar (data/recordings/<matchId>.json,
keys written by core/obs_recorder.py _write_sidecar) -> merged video windows.
  * Death window = an own-death ChampionKill bookmark (name == "ChampionKill"
    and own_death true) at game time t -> game span [t - 20 s, t + 3 s], then
    padded by ReelSettings.pad_before_s / pad_after_s.
  * Game time -> video time uses the core/vod_alignment.py convention
    video_time = game_time + offset, with the offset of the alignment anchor
    in force at the death (alignment.anchors), falling back to
    game_time_offset_s when the sidecar carries no anchors.
  * Start clamped at 0; a window that ends at or before 0 is dropped.
  * Overlapping (and touching) windows merge.
  * Each window carries the core/pgr_event_report.py render() lines whose
    t_ms falls inside its game span (additive; empty when there is no report
    or no line there - never invented).

THIN IO: build_reel() cuts data/recordings/<matchId>/deaths.mp4 with an
ffmpeg subprocess (CREATE_NO_WINDOW): stream copy per segment, concat with
faststart, a single segment moved instead of concatenated, temp files cleaned
in a finally block, progress -1 means error. It reads the file back (size > 0,
plus ffprobe duration when ffprobe is available) and records the clip in the
sidecar's ``death_reel`` block via an atomic write. That block is what the
RM-640 retention reader checks (core/vod_retention.py rows_from_sidecar:
death_reel.path must stat to a size > 0). If ffmpeg is absent the runner
returns status "ffmpeg_missing" and does nothing at all.

Stream copy snaps cuts to keyframes, so the OBS keyframe interval should be
1-2 s. That is an operator setting (ADR-016); RC never writes OBS config.

Nothing in RC calls build_reel() yet (the recorder lives on its own branch);
`python -m core.highlight_reel <sidecar.json>` previews the windows, and
`--build` cuts the reel.

Optional replay-buffer variant: replay_buffer_request() is a documented hook
ONLY. It returns a descriptor a future producer may act on (SaveReplayBuffer a
few seconds after an own death, linked into core/aftergame_summary.py
clips_review); it never calls OBS.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _APP_DIR / "config" / "coach_settings.json"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

REEL_NAME = "deaths.mp4"
REEL_SCHEMA = 1

# Our own constants. The 20 s lead-in / 3 s tail come from the directive's
# design text for X-39 (enough to see the setup of a death plus the kill
# itself); they are settings, not measurements. Padding defaults to zero.
DEATH_BEFORE_S = 20.0
DEATH_AFTER_S = 3.0

# Our own: a few seconds after the death so the buffer holds the death itself.
REPLAY_BUFFER_DELAY_S = 5.0

# Our own subprocess ceilings: a stream-copy cut of a short window is
# seconds of IO; the concat of a whole match's deaths is still well under this.
CUT_TIMEOUT_S = 300
PROBE_TIMEOUT_S = 30

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


# -- pure ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReelSettings:
    death_before_s: float = DEATH_BEFORE_S
    death_after_s: float = DEATH_AFTER_S
    pad_before_s: float = 0.0
    pad_after_s: float = 0.0


@dataclass(frozen=True)
class Window:
    start_s: float          # video seconds, clamped >= 0
    end_s: float            # video seconds
    game_start_s: float     # game seconds (unclamped)
    game_end_s: float
    events: tuple = ()      # source bookmarks (dict copies)
    annotations: tuple = field(default=())  # PGR lines (dict copies)

    def to_dict(self) -> dict:
        return {"start_s": round(self.start_s, 3), "end_s": round(self.end_s, 3),
                "game_start_s": round(self.game_start_s, 3),
                "game_end_s": round(self.game_end_s, 3),
                "event_ids": [e.get("event_id") for e in self.events],
                "annotations": [dict(a) for a in self.annotations]}


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _anchors(sidecar: dict) -> list:
    al = sidecar.get("alignment") if isinstance(sidecar.get("alignment"), dict) else {}
    out = []
    for a in al.get("anchors") or []:
        if isinstance(a, dict):
            g, o = _num(a.get("game_time")), _num(a.get("offset_s"))
            if g is not None and o is not None:
                out.append((g, o))
    out.sort()
    return out


def offset_for(sidecar: dict, game_time: float) -> float:
    """Offset (video - game seconds) in force at ``game_time``.

    Mirrors core/vod_alignment.py: the last anchor at or before game_time, the
    first anchor for an earlier time; game_time_offset_s with no anchors."""
    anchors = _anchors(sidecar)
    if not anchors:
        return _num(sidecar.get("game_time_offset_s")) or 0.0
    chosen = anchors[0]
    for a in anchors:
        if a[0] <= game_time + 1e-9:
            chosen = a
        else:
            break
    return chosen[1]


def video_time_for(sidecar: dict, game_time: float) -> float:
    """Video seconds for a game time, clamped >= 0. A PGR row seeks with this
    (t_ms / 1000 -> video_time_for)."""
    gt = _num(game_time) or 0.0
    return max(0.0, gt + offset_for(sidecar, gt))


def death_bookmarks(sidecar: dict) -> list:
    """Own-death ChampionKill bookmarks with a numeric game_time, by time."""
    out = []
    bms = sidecar.get("bookmarks") if isinstance(sidecar, dict) else None
    for b in bms if isinstance(bms, list) else []:
        if not isinstance(b, dict):
            continue
        if b.get("name") != "ChampionKill" or b.get("own_death") is not True:
            continue
        if _num(b.get("game_time")) is None:
            continue
        out.append(b)
    out.sort(key=lambda b: _num(b.get("game_time")))
    return out


def annotations_for(pgr_report: Any, game_start_s: float, game_end_s: float) -> tuple:
    """PGR render() lines whose t_ms lies inside [game_start_s, game_end_s]."""
    if not isinstance(pgr_report, dict):
        return ()
    hits = []
    for ln in pgr_report.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        t = _num(ln.get("t_ms"))
        if t is None:
            continue
        if game_start_s <= t / 1000.0 <= game_end_s:
            hits.append(dict(ln))
    hits.sort(key=lambda ln: (_num(ln.get("t_ms")), str(ln.get("criterion"))))
    return tuple(hits)


def merge_windows(windows: Iterable[Window]) -> list:
    """Merge overlapping or touching windows (sorted by start)."""
    out: list = []
    for w in sorted(windows, key=lambda w: (w.start_s, w.end_s)):
        if out and w.start_s <= out[-1].end_s:
            cur = out[-1]
            seen = set()
            anns = []
            for a in sorted(cur.annotations + w.annotations,
                            key=lambda a: (_num(a.get("t_ms")), str(a.get("criterion")))):
                key = json.dumps(a, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    anns.append(a)
            out[-1] = Window(cur.start_s, max(cur.end_s, w.end_s),
                             min(cur.game_start_s, w.game_start_s),
                             max(cur.game_end_s, w.game_end_s),
                             cur.events + w.events, tuple(anns))
        else:
            out.append(w)
    return out


def build_windows(sidecar: dict, settings: Optional[ReelSettings] = None,
                  pgr_report: Any = None) -> list:
    """Sidecar -> merged video windows for the death reel. [] = zero deaths."""
    s = settings or ReelSettings()
    raw = []
    for b in death_bookmarks(sidecar):
        t = _num(b.get("game_time"))
        g0 = t - s.death_before_s - s.pad_before_s
        g1 = t + s.death_after_s + s.pad_after_s
        off = offset_for(sidecar, t)
        v0, v1 = g0 + off, g1 + off
        if v1 <= 0:
            continue
        raw.append(Window(max(0.0, v0), v1, g0, g1, (dict(b),),
                          annotations_for(pgr_report, g0, g1)))
    return merge_windows(raw)


def replay_buffer_request(bookmark: Any, delay_s: float = REPLAY_BUFFER_DELAY_S) -> Optional[dict]:
    """HOOK ONLY (no OBS call): the descriptor of the optional replay-buffer
    variant for an own death. A future producer that owns the replay buffer
    (ADR-016 ownership rule) may send SaveReplayBuffer ``after_s`` seconds
    after the death and link the saved file into the aftergame clips_review
    line. None for anything that is not an own death."""
    if not isinstance(bookmark, dict) or bookmark.get("name") != "ChampionKill" \
            or bookmark.get("own_death") is not True:
        return None
    t = _num(bookmark.get("game_time"))
    if t is None:
        return None
    return {"request": "SaveReplayBuffer", "game_time": t, "after_s": float(delay_s)}


# -- thin IO ---------------------------------------------------------------------


@dataclass
class ReelResult:
    status: str             # ok | ffmpeg_missing | no_deaths | not_final |
    #                         no_source | source_missing | bad_sidecar |
    #                         error | read_back_failed
    path: Optional[str] = None
    size_bytes: Optional[int] = None
    duration_s: Optional[float] = None
    windows: list = field(default_factory=list)
    detail: str = ""


def _is_file(p: Any) -> bool:
    try:
        return bool(p) and Path(str(p)).is_file()
    except OSError:
        return False


def locate_ffmpeg(config_path: Any = None,
                  which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """obs.record.ffmpeg_path from the gitignored config if it names a file,
    else ffmpeg on PATH, else None. Never downloads anything."""
    cfg = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        doc = json.loads(cfg.read_text(encoding="utf-8"))
        rec = ((doc.get("obs") or {}).get("record") or {})
        cand = rec.get("ffmpeg_path") if isinstance(rec, dict) else None
        if _is_file(cand):
            return str(cand)
    except (OSError, ValueError, AttributeError):
        pass
    return which("ffmpeg") or None


def locate_ffprobe(ffmpeg: Optional[str],
                   which: Callable[[str], Optional[str]] = shutil.which) -> Optional[str]:
    """ffprobe beside ffmpeg, else on PATH, else None (duration is optional)."""
    if ffmpeg:
        p = Path(ffmpeg)
        sib = p.with_name("ffprobe" + p.suffix)
        if _is_file(sib):
            return str(sib)
    return which("ffprobe") or None


def _atomic_write_json(path: Path, data: dict) -> None:
    from core.polled_json import atomic_write_bytes
    atomic_write_bytes(Path(path), json.dumps(data, indent=2, ensure_ascii=True).encode("ascii"))


def _on_windows() -> bool:
    """Host check behind one seam, so the no-window spawn contract is tested
    on a non-Windows CI runner by faking the host instead of skipping."""
    return sys.platform == "win32"


def _run(runner: Callable, cmd: list, timeout: int) -> subprocess.CompletedProcess:
    # POSIX subprocess raises on a non-zero creationflags, so 0 off Windows.
    return runner(cmd, capture_output=True, timeout=timeout,
                  creationflags=CREATE_NO_WINDOW if _on_windows() else 0)


def _probe_duration(runner: Callable, ffprobe: Optional[str], path: Path) -> Optional[float]:
    if not ffprobe:
        return None
    try:
        res = _run(runner, [ffprobe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                   PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    out = res.stdout.decode("ascii", "replace") if isinstance(res.stdout, bytes) else str(res.stdout)
    d = _num(out.strip())
    return d if d is not None and d > 0 else None


def _cut_cmd(ffmpeg: str, src: str, w: Window, out: Path) -> list:
    return [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-ss", f"{w.start_s:.3f}", "-i", src, "-t", f"{w.end_s - w.start_s:.3f}",
            "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", str(out)]


def _concat_cmd(ffmpeg: str, listfile: Path, out: Path) -> list:
    return [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listfile),
            "-map", "0", "-c", "copy", "-movflags", "+faststart", str(out)]


def build_reel(sidecar_path: Any, *, ffmpeg: Optional[str] = None,
               ffprobe: Any = "auto",
               settings: Optional[ReelSettings] = None, pgr_report: Any = None,
               runner: Callable = subprocess.run,
               progress: Optional[Callable[[int], None]] = None) -> ReelResult:
    """Cut <sidecar dir>/<matchId>/deaths.mp4 and record it in the sidecar."""
    def report(pct: int) -> None:
        if progress is not None:
            try:
                progress(pct)
            except Exception:  # noqa: BLE001 - a progress sink never breaks a cut
                pass

    sp = Path(sidecar_path)
    ff = ffmpeg or locate_ffmpeg()
    if not ff:
        return ReelResult("ffmpeg_missing",
                          detail="ffmpeg not found (obs.record.ffmpeg_path or PATH)")
    try:
        doc = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ReelResult("bad_sidecar", detail=str(exc))
    if not isinstance(doc, dict):
        return ReelResult("bad_sidecar", detail="not an object")
    if doc.get("status") != "final":
        return ReelResult("not_final")
    windows = build_windows(doc, settings, pgr_report)
    if not windows:
        doc["death_reel"] = {"schema": REEL_SCHEMA, "status": "no_deaths", "path": None,
                             "created_at": time.time()}
        try:
            _atomic_write_json(sp, doc)
        except OSError as exc:
            return ReelResult("error", detail=f"sidecar write: {exc}")
        report(100)
        return ReelResult("no_deaths")
    src = doc.get("obs_output_path")
    if not src:
        return ReelResult("no_source", windows=windows)
    if not _is_file(src):
        return ReelResult("source_missing", windows=windows)
    if ffprobe == "auto":  # explicit None = skip the duration probe
        ffprobe = locate_ffprobe(ff)

    mid = _SAFE_ID.sub("", str(doc.get("match_id") or sp.stem))[:64] or _SAFE_ID.sub("", sp.stem)
    out_dir = sp.parent / mid
    out = out_dir / REEL_NAME
    tmp = out_dir / f".reel-tmp-{os.getpid()}"
    made_dir = not out_dir.exists()
    status, detail = "error", ""
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        segs = []
        n = len(windows)
        for i, w in enumerate(windows):
            seg = tmp / f"seg{i:03d}.mp4"
            res = _run(runner, _cut_cmd(ff, str(src), w, seg), CUT_TIMEOUT_S)
            if res.returncode != 0 or not seg.is_file():
                detail = f"cut {i} failed rc={res.returncode}"
                raise RuntimeError(detail)
            segs.append(seg)
            report(int(80 * (i + 1) / (n + 1)))
        if len(segs) == 1:
            final = segs[0]
        else:
            listfile = tmp / "list.txt"
            listfile.write_text("".join(
                "file '" + s.as_posix().replace("'", "'\\''") + "'\n" for s in segs),
                encoding="utf-8")
            final = tmp / "concat.mp4"
            res = _run(runner, _concat_cmd(ff, listfile, final), CUT_TIMEOUT_S)
            if res.returncode != 0 or not final.is_file():
                detail = f"concat failed rc={res.returncode}"
                raise RuntimeError(detail)
        report(85)
        os.replace(final, out)
        # Read back what landed on disk (what RM-640 retention will stat).
        size = out.stat().st_size
        if size <= 0:
            status, detail = "read_back_failed", "empty output"
            raise RuntimeError(detail)
        duration = _probe_duration(runner, ffprobe, out)
        doc["death_reel"] = {
            "schema": REEL_SCHEMA, "status": "ok", "path": str(out),
            "size_bytes": size, "duration_s": duration, "read_back_ok": True,
            "segments": n, "source": str(src), "created_at": time.time(),
            "windows": [w.to_dict() for w in windows],
        }
        _atomic_write_json(sp, doc)
        status = "ok"
        report(100)
        return ReelResult("ok", str(out), size, duration, windows)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        detail = detail or str(exc)
        _log.warning("death reel %s failed: %s", mid, detail)
        if status == "read_back_failed":
            try:
                out.unlink()  # our own just-made empty output, never a recording
            except OSError:
                pass
        report(-1)
        return ReelResult(status if status != "ok" else "error", windows=windows,
                          detail=detail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if made_dir and status != "ok":
            try:
                out_dir.rmdir()  # only if empty
            except OSError:
                pass


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    build = "--build" in args
    paths = [a for a in args if not a.startswith("--")]
    if len(paths) != 1:
        print("usage: python -m core.highlight_reel <sidecar.json> [--build]")
        return 2
    if build:
        res = build_reel(paths[0])
        print(f"{res.status} {res.path or ''} {res.detail}".strip())
        return 0 if res.status in ("ok", "no_deaths") else 1
    try:
        doc = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"bad sidecar: {exc}")
        return 1
    ws = build_windows(doc if isinstance(doc, dict) else {})
    print(f"{len(ws)} window(s); ffmpeg={'found' if locate_ffmpeg() else 'missing'}")
    for w in ws:
        print(f"  video {w.start_s:9.3f} -> {w.end_s:9.3f}  ({len(w.events)} death(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
