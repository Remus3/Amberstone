# arch: retention policy + report over data/ | section=core | frozen=no
"""core/data_retention.py - report-first retention policy for the data/ corpus.

RM-117 (ii). `core/log_retention.py` is the shape precedent: a pure sweep
function plus module-level policy constants. This module deliberately does
NOT copy log_retention's second half - log_retention deletes on a timer, and
that is exactly the wrong default for data/, whose mass is production match
history and one-off operator safety copies.

WHY THIS EXISTS AND WHAT THE PREMISE ACTUALLY IS
------------------------------------------------
The ROADMAP row for this item reads "6 GB .rofl corpus growing hourly".
Both halves are measured FALSE (2026-08-04, walk of data/):

    data/ total          10.11 GB across 2106 files
    .rofl under data/    ZERO files

The real distribution, by extension:

    .db              5.350 GB   n=11
    .bak_predupe     1.871 GB   n=1
    .bak-20260720    1.848 GB   n=1
    .json            0.630 GB   n=1458
    .jsonl           0.288 GB   n=18
    .html            0.054 GB   n=115

and by file, the head of the distribution is four objects:

    3350.7 MB  data/riot_api_cache.db
    1870.6 MB  data/rewind_history.db.bak_predupe
    1870.6 MB  data/rewind_history.db
    1848.3 MB  data/rewind_history.db.bak-20260720

So the dominant file class is SQLite, not replays, and 3.72 GB of the total
is two backups of a single 1.87 GB database. A retention mechanism aimed at
an hourly-growing replay corpus would have reclaimed nothing.

THE FOUR CLASSES ARE NOT ONE PROBLEM
------------------------------------
Folding these into one sweep is the failure mode this module is built to
avoid. Each class gets its own verdict:

  STALE_BACKUP      (CLASS_STALE_BACKUP / VERDICT_RECOMMEND_OPERATOR)
      One-off `.bak*` snapshots taken by hand before a destructive
      migration. `rewind_history.db.bak-20260720` is the item-971 .rofl
      sidecar backfill safety copy; `rewind_history.db.bak_predupe` is a
      pre-dedup copy. NOTHING in the repo reads either - grep for
      "predupe" returns only docs/LEDGER.md prose. They are still the only
      rollback for a hand-run migration, so age is evidence they are cold,
      not authority to delete them. Recommend, never sweep.

  UNBOUNDED_CACHE   (CLASS_UNBOUNDED_CACHE / VERDICT_ALARM_ONLY)
      `data/riot_api_cache.db`. `cache_immutable` never expires BY DESIGN
      (see core/riot_api_cache.py) and the eviction policy is an open
      operator decision filed as RM-153. This module does not pre-empt
      that decision; it reports the number and alarms past a cap. Note the
      RM-153 Windows trap: the DB is WAL, so `-wal` and `-shm` are PART of
      the database and are never candidates on their own.

  APPEND_LOG        (CLASS_APPEND_LOG / VERDICT_AUTO_ELIGIBLE)
      `data/*_shadow.jsonl` and `data/*_trace.jsonl`. Thirteen fail-soft
      shadow writers under core/ append one line per coarse game state on
      the hot path with no cap and no rotation (core/det_coach_shadow.py
      is representative). This is the only class whose files are
      regenerable-by-accrual and whose loss costs nothing but shadow
      history, so it is the only class marked auto-eligible.

  SUPERSEDED_PATCH  (CLASS_SUPERSEDED_PATCH / VERDICT_RECOMMEND_OPERATOR)
      Per-patch generation directories where newer generations exist -
      e.g. `data/daemon_slayer/laning_scenarios/16.11.1` at 65.6 MB with
      16.12.1 and 16.13.1 both present. Regenerable, but the DS data seam
      is not this module's to sweep.

  RETAIN            (CLASS_RETAIN / VERDICT_RETAIN)
      Everything else, including `data/rewind_history.db` itself. That
      file is 1.87 GB and looks like the second-biggest target, but it has
      a wide live reader set (coaches/replay_coach.py,
      coaches/champ_pool_recommender.py, agents/agent2_backend/*, and the
      DS calibration tables are derived from it) and its mtime is not
      advancing hourly. It is production data, not corpus growth.

SAFETY CONTRACT
---------------
`scan`, `plan`, `render_report` and `game_information_manifest` are
READ-ONLY. They stat files and never open one for writing, never unlink,
never rename. `tests/test_data_retention.py` pins that with a before/after
tree comparison so a later edit cannot quietly turn the report into a
delete.

POLICY RANGE GATE (RM-363)
--------------------------
Every cap here feeds a `>` comparison, so at 0 or below the predicate
INVERTS: the knob that exists to bound the corpus marks everything it can
reach eligible instead. `plan` therefore raises ValueError on any cap
below 1, before it touches the filesystem - the same shape RM-161 closed
in three sibling retention knobs (LEDGER 1201). `keep_patches` is the one
knob that is FLOORED rather than rejected, because returning the newest
generation is a contract bug in `_superseded_patch_dirs` at any keep
value, not merely a bad input; see the comment there.

`apply` exists so the policy has an enforcement arm, but it is inert by
construction and NOTHING in RC calls it: it refuses unless handed
CONFIRM_TOKEN, it refuses every class whose verdict is not
VERDICT_AUTO_ELIGIBLE, and it refuses any path that does not resolve
inside the scanned root. There is no --apply flag on the CLI. Deleting
existing bytes under data/ is an operator call.

RIOT TERMS CONDITION (v) - TERMINATION
--------------------------------------
`game_information_manifest()` answers "on termination, delete all Game
Information". It enumerates every path under data/ holding Riot-derived
match, account or live-game data, with sizes, grouped by category, and it
is read-only like the rest. Executing that deletion is deliberately not
implemented here - see the module report for the recommendation.

Run:
    python -m core.data_retention
    python -m core.data_retention --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# -- classes -------------------------------------------------------------

CLASS_STALE_BACKUP = "STALE_BACKUP"
CLASS_UNBOUNDED_CACHE = "UNBOUNDED_CACHE"
CLASS_APPEND_LOG = "APPEND_LOG"
CLASS_SUPERSEDED_PATCH = "SUPERSEDED_PATCH"
CLASS_RETAIN = "RETAIN"

ALL_CLASSES = (
    CLASS_STALE_BACKUP,
    CLASS_UNBOUNDED_CACHE,
    CLASS_APPEND_LOG,
    CLASS_SUPERSEDED_PATCH,
    CLASS_RETAIN,
)

# -- verdicts ------------------------------------------------------------

VERDICT_RECOMMEND_OPERATOR = "recommend-operator"
VERDICT_ALARM_ONLY = "alarm-only"
VERDICT_AUTO_ELIGIBLE = "auto-eligible"
VERDICT_RETAIN = "retain"

VERDICTS: dict[str, str] = {
    CLASS_STALE_BACKUP: VERDICT_RECOMMEND_OPERATOR,
    CLASS_UNBOUNDED_CACHE: VERDICT_ALARM_ONLY,
    CLASS_APPEND_LOG: VERDICT_AUTO_ELIGIBLE,
    CLASS_SUPERSEDED_PATCH: VERDICT_RECOMMEND_OPERATOR,
    CLASS_RETAIN: VERDICT_RETAIN,
}

# -- policy defaults -----------------------------------------------------

DEFAULT_MAX_BACKUP_AGE_DAYS = 30
DEFAULT_MAX_APPEND_LOG_AGE_DAYS = 30
DEFAULT_MAX_CACHE_BYTES = 2 * 1024**3   # matches scripts/db_size_monitor.py
DEFAULT_KEEP_PATCHES = 2                # current + previous, per item 397

# The only string apply() accepts as authorization.
CONFIRM_TOKEN = "yes-delete-auto-eligible"

# -- recognisers ---------------------------------------------------------

# Matches ".bak", ".bak-<tag>", ".bak_<tag>"; does NOT match ".baker".
_BACKUP_RE = re.compile(r"\.bak(?:$|[-_.])")
# Dotted numeric directory name, e.g. "16.12.1".
_PATCH_DIR_RE = re.compile(r"^\d+(?:\.\d+)+$")

# Named, not pattern-matched: growth here is a documented DESIGN choice
# with an open policy decision (RM-153). Adding a name to this set is a
# claim that the file grows without bound and nothing bounds it.
UNBOUNDED_CACHE_NAMES = frozenset({"riot_api_cache.db"})

# SQLite WAL sidecars are part of their database. They are never candidates
# on their own - separating them corrupts the DB (RM-153 Windows trap).
_DB_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _is_append_log(name: str) -> bool:
    return name.endswith("_shadow.jsonl") or name.endswith("_trace.jsonl")


def _version_key(name: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return ()


# -- Game Information (Riot terms condition (v)) -------------------------

# Categories of Riot-derived data held under data/. Each entry is
# (category, predicate over the data/-relative posix path).
_GAME_INFO_RULES: tuple[tuple[str, str], ...] = (
    ("riot_api_cache", "riot_api_cache.db"),
    ("match_history", "rewind_history.db"),
    ("match_history", "match_history.db"),
    ("match_metrics", "match_metrics.db"),
    ("per_mode_db", "db/"),
    ("live_game_state", "_coaching_data.json"),
    ("live_game_shadow", "_shadow.jsonl"),
    ("live_game_shadow", "_trace.jsonl"),
    ("replay_corpus", "rewind_cache/"),
    ("replay_corpus", "event_captures/"),
    ("replay_corpus", ".rofl"),
    ("coach_cache", "coach_cache/"),
)


def _base_name(rel: str) -> str:
    """Strip a backup tag and/or a SQLite sidecar suffix off a path.

    A termination clause reaches the COPIES, not just the live file.
    Measured on the live tree 2026-08-04: matching on the literal name
    alone missed `rewind_history.db.bak_predupe` and
    `rewind_history.db.bak-20260720`, i.e. 3.72 GB of the same match data
    - the majority of the corpus - because neither name ENDS with
    "rewind_history.db". The `-wal`/`-shm` sidecars hold unflushed rows
    and are equally part of the database.
    """
    out = rel
    for sfx in _DB_SIDECAR_SUFFIXES:
        if out.endswith(sfx):
            out = out[: -len(sfx)]
            break
    m = _BACKUP_RE.search(out)
    if m:
        out = out[: m.start()]
    return out


def _game_info_category(rel: str) -> Optional[str]:
    """Return the Game-Information category for a data/-relative path.

    Deliberately conservative on both sides. DDragon-derived static assets
    (icons, champion stat tables, the DS engine registries) are Riot
    CONTENT, not per-game Game Information, and are excluded; anything
    holding match, account or live-game state is included - including its
    backups and its SQLite sidecars, see `_base_name`.
    """
    low = rel.lower()
    forms = (low, _base_name(low))
    for category, needle in _GAME_INFO_RULES:
        if needle.endswith("/"):
            if low.startswith(needle) or ("/" + needle) in low:
                return category
            continue
        for form in forms:
            if form.endswith(needle) or form.rsplit("/", 1)[-1] == needle:
                return category
    return None


# -- data model ----------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One file or directory, classified, with its size and age."""

    path: Path
    klass: str
    size_bytes: int
    age_days: float
    eligible: bool = False
    reason: str = ""


@dataclass
class RetentionPlan:
    root: Path
    candidates: list[Candidate] = field(default_factory=list)
    verdicts: dict[str, str] = field(default_factory=dict)
    bytes_by_class: dict[str, int] = field(default_factory=dict)
    counts_by_class: dict[str, int] = field(default_factory=dict)
    policy: dict = field(default_factory=dict)

    @property
    def eligible(self) -> list[Candidate]:
        return [c for c in self.candidates if c.eligible]

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "policy": self.policy,
            "verdicts": self.verdicts,
            "bytes_by_class": self.bytes_by_class,
            "counts_by_class": self.counts_by_class,
            "candidates": [
                {
                    "path": str(c.path),
                    "class": c.klass,
                    "bytes": c.size_bytes,
                    "age_days": round(c.age_days, 2),
                    "eligible": c.eligible,
                    "reason": c.reason,
                    "verdict": self.verdicts.get(c.klass, VERDICT_RETAIN),
                }
                for c in self.candidates
            ],
        }


@dataclass
class GameInformationManifest:
    """Everything condition (v) would have to reach. Read-only."""

    root: Path
    paths: list[Path] = field(default_factory=list)
    total_bytes: int = 0
    by_category: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "total_bytes": self.total_bytes,
            "path_count": len(self.paths),
            "by_category": self.by_category,
        }


# -- filesystem helpers (stat only) --------------------------------------


def _stat(p: Path) -> Optional[os.stat_result]:
    try:
        return p.stat()
    except OSError:
        return None


def _dir_bytes(p: Path) -> int:
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(p):
            for fn in filenames:
                st = _stat(Path(dirpath) / fn)
                if st is not None:
                    total += st.st_size
    except OSError:
        pass
    return total


def _age_days(st: os.stat_result, now: float) -> float:
    return max(0.0, (now - st.st_mtime) / 86400.0)


# -- classification ------------------------------------------------------


def _classify_file(name: str) -> str:
    if any(name.endswith(sfx) for sfx in _DB_SIDECAR_SUFFIXES):
        return CLASS_RETAIN
    if _BACKUP_RE.search(name):
        return CLASS_STALE_BACKUP
    if name in UNBOUNDED_CACHE_NAMES:
        return CLASS_UNBOUNDED_CACHE
    if _is_append_log(name):
        return CLASS_APPEND_LOG
    return CLASS_RETAIN


def _superseded_patch_dirs(root: Path, keep_patches: int) -> list[Path]:
    """Directories whose name is a version and which a newer sibling supersedes."""
    groups: dict[Path, list[Path]] = {}
    try:
        for dirpath, dirnames, _filenames in os.walk(root):
            parent = Path(dirpath)
            versioned = [d for d in dirnames if _PATCH_DIR_RE.match(d)]
            if len(versioned) > 1:
                groups[parent] = [parent / d for d in versioned]
    except OSError:
        return []

    superseded: list[Path] = []
    for _parent, dirs in groups.items():
        ordered = sorted(dirs, key=lambda p: _version_key(p.name), reverse=True)
        # RM-363: floor at 1, not 0. "Superseded" is defined by this
        # function's own docstring as "a newer sibling supersedes it", and
        # the newest generation has no newer sibling - so returning it is
        # wrong at ANY keep value, not merely at a bad one. `max(0, ...)`
        # made ordered[0:] the WHOLE list, which handed the current live
        # generation (data/daemon_slayer/<current patch>) to a report that
        # recommends deletion. Floored rather than rejected because a
        # caller asking to keep as little as possible has a coherent
        # intent; asking to delete the generation in use does not.
        superseded.extend(ordered[max(1, keep_patches):])
    return superseded


def scan(
    data_dir: Path | str,
    *,
    keep_patches: int = DEFAULT_KEEP_PATCHES,
    now: Optional[float] = None,
) -> list[Candidate]:
    """Classify everything under `data_dir`. Read-only.

    Returns one Candidate per file, plus one per superseded patch
    directory. Files inside a superseded patch directory are folded into
    that directory's Candidate rather than reported twice.
    """
    import time

    root = Path(data_dir)
    if not root.is_dir():
        return []
    now = time.time() if now is None else now

    out: list[Candidate] = []

    superseded = _superseded_patch_dirs(root, keep_patches)
    superseded_set = {p.resolve() for p in superseded}
    for d in superseded:
        st = _stat(d)
        out.append(Candidate(
            path=d,
            klass=CLASS_SUPERSEDED_PATCH,
            size_bytes=_dir_bytes(d),
            age_days=_age_days(st, now) if st else 0.0,
            eligible=True,
            reason=f"superseded generation; newest {keep_patches} kept",
        ))

    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        # Do not descend into a superseded generation - it is one candidate.
        if here.resolve() in superseded_set:
            dirnames[:] = []
            continue
        dirnames[:] = [
            d for d in dirnames if (here / d).resolve() not in superseded_set
        ]
        for fn in filenames:
            p = here / fn
            st = _stat(p)
            if st is None:
                continue
            out.append(Candidate(
                path=p,
                klass=_classify_file(fn),
                size_bytes=st.st_size,
                age_days=_age_days(st, now),
            ))
    return out


# -- policy --------------------------------------------------------------


def _validate_policy(**caps: int) -> None:
    """Refuse a cap that can only mean "everything". RM-363, RM-161 shape.

    Runs BEFORE any filesystem work, deliberately: scan() early-returns on
    a missing root, and a range check sitting after that would let a
    caller point a destructive policy at an absent path and be told
    nothing was wrong.

    Each cap is reported by NAME so a caller with several knobs is told
    which one it got wrong, and every offending cap is named in one pass
    rather than one per round trip.
    """
    bad = [f"{name}={value!r}" for name, value in caps.items() if value < 1]
    if bad:
        raise ValueError(
            "retention cap below 1 erases everything it can reach: "
            + ", ".join(sorted(bad))
            + " (a cap bounds a corpus; it is not a delete-all switch)"
        )


def plan(
    data_dir: Path | str,
    *,
    max_backup_age_days: int = DEFAULT_MAX_BACKUP_AGE_DAYS,
    max_append_log_age_days: int = DEFAULT_MAX_APPEND_LOG_AGE_DAYS,
    max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
    keep_patches: int = DEFAULT_KEEP_PATCHES,
    now: Optional[float] = None,
) -> RetentionPlan:
    """Build the retention plan for `data_dir`. Read-only - deletes nothing.

    Eligibility is per class and never implies permission; permission is
    the class VERDICT, and only VERDICT_AUTO_ELIGIBLE grants any.

    Raises ValueError on a cap below 1 (RM-363). Every cap here feeds a
    `>` comparison, so at 0 or below the predicate inverts and EVERY
    record it can reach becomes eligible - the knob that exists to bound
    the corpus erases it instead. CLASS_APPEND_LOG carries the only
    VERDICT_AUTO_ELIGIBLE verdict, so that inversion reaches
    `target.unlink()` in apply() on files a live writer holds open.
    """
    _validate_policy(
        max_backup_age_days=max_backup_age_days,
        max_append_log_age_days=max_append_log_age_days,
        max_cache_bytes=max_cache_bytes,
    )
    root = Path(data_dir)
    raw = scan(root, keep_patches=keep_patches, now=now)

    candidates: list[Candidate] = []
    for c in raw:
        if c.klass == CLASS_RETAIN:
            continue
        if c.klass == CLASS_STALE_BACKUP:
            elig = c.age_days > max_backup_age_days
            reason = (
                f"backup, {c.age_days:.0f}d old (floor {max_backup_age_days}d)"
                if elig else
                f"backup, {c.age_days:.0f}d old - under the {max_backup_age_days}d floor"
            )
        elif c.klass == CLASS_APPEND_LOG:
            elig = c.age_days > max_append_log_age_days
            reason = (
                f"append log idle {c.age_days:.0f}d (floor {max_append_log_age_days}d)"
                if elig else
                f"append log active, idle {c.age_days:.0f}d"
            )
        elif c.klass == CLASS_UNBOUNDED_CACHE:
            elig = c.size_bytes > max_cache_bytes
            reason = (
                f"over the {_fmt(max_cache_bytes)} alarm cap; policy is RM-153"
                if elig else
                f"under the {_fmt(max_cache_bytes)} alarm cap"
            )
        else:  # CLASS_SUPERSEDED_PATCH
            elig = c.eligible
            reason = c.reason
        candidates.append(Candidate(
            path=c.path, klass=c.klass, size_bytes=c.size_bytes,
            age_days=c.age_days, eligible=elig, reason=reason,
        ))

    bytes_by_class = {k: 0 for k in ALL_CLASSES if k != CLASS_RETAIN}
    counts_by_class = {k: 0 for k in ALL_CLASSES if k != CLASS_RETAIN}
    for c in candidates:
        bytes_by_class[c.klass] += c.size_bytes
        counts_by_class[c.klass] += 1

    candidates.sort(key=lambda c: c.size_bytes, reverse=True)

    return RetentionPlan(
        root=root,
        candidates=candidates,
        verdicts=dict(VERDICTS),
        bytes_by_class=bytes_by_class,
        counts_by_class=counts_by_class,
        policy={
            "max_backup_age_days": max_backup_age_days,
            "max_append_log_age_days": max_append_log_age_days,
            "max_cache_bytes": max_cache_bytes,
            "keep_patches": keep_patches,
        },
    )


def apply(rplan: RetentionPlan, confirm: Optional[str] = None) -> dict:
    """Enforcement arm. Inert unless explicitly authorized; NOTHING calls it.

    Three independent gates, all of which must open:
      1. `confirm` must equal CONFIRM_TOKEN.
      2. the candidate's class verdict must be VERDICT_AUTO_ELIGIBLE.
      3. the candidate must resolve inside `rplan.root`.

    Returns a result dict; never raises. Deleting anything under data/ that
    is not an aged append log is an operator call, not this function's.
    """
    result = {
        "applied": False,
        "deleted": 0,
        "bytes_freed": 0,
        "refused_classes": [],
        "errors": [],
    }
    present = {c.klass for c in rplan.candidates}

    if confirm != CONFIRM_TOKEN:
        result["refused_classes"] = sorted(present)
        return result

    allowed = {k for k in present if VERDICTS.get(k) == VERDICT_AUTO_ELIGIBLE}
    result["refused_classes"] = sorted(present - allowed)
    result["applied"] = True

    try:
        root_resolved = rplan.root.resolve()
    except OSError:
        result["applied"] = False
        return result

    for c in rplan.candidates:
        if c.klass not in allowed or not c.eligible:
            continue
        try:
            target = c.path.resolve()
            if root_resolved not in target.parents and target != root_resolved:
                result["errors"].append(f"outside root, skipped: {c.path}")
                continue
            size = c.size_bytes
            target.unlink()
            result["deleted"] += 1
            result["bytes_freed"] += size
        except OSError as exc:
            result["errors"].append(f"{c.path}: {exc}")
    return result


# -- Riot terms condition (v) --------------------------------------------


def game_information_manifest(
    data_dir: Path | str,
) -> GameInformationManifest:
    """Enumerate every path under data/ holding Riot-derived Game Information.

    This is the condition (v) answer surface: a termination clause requiring
    deletion of all Game Information needs a complete, sized, categorised
    path list before anything can be deleted. Read-only.
    """
    root = Path(data_dir)
    manifest = GameInformationManifest(root=root)
    if not root.is_dir():
        return manifest

    for dirpath, _dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        for fn in filenames:
            p = here / fn
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue
            category = _game_info_category(rel)
            if category is None:
                continue
            st = _stat(p)
            size = st.st_size if st else 0
            manifest.paths.append(p)
            manifest.total_bytes += size
            bucket = manifest.by_category.setdefault(
                category, {"bytes": 0, "count": 0, "paths": []}
            )
            bucket["bytes"] += size
            bucket["count"] += 1
            bucket["paths"].append(rel)
    return manifest


# -- rendering -----------------------------------------------------------


def _fmt(b: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(b)
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


def render_report(rplan: RetentionPlan, top: int = 25) -> str:
    """Human-readable dry-run report. ASCII only. Read-only."""
    lines: list[str] = []
    lines.append(f"data/ retention plan - root {rplan.root}")
    lines.append("-" * 72)
    total = sum(rplan.bytes_by_class.values())
    lines.append(f"reclaimable-class mass: {_fmt(total)}")
    lines.append("")
    for klass in ALL_CLASSES:
        if klass == CLASS_RETAIN:
            continue
        lines.append(
            f"  {klass:<18} {_fmt(rplan.bytes_by_class.get(klass, 0)):>10}"
            f"  n={rplan.counts_by_class.get(klass, 0):<5}"
            f" verdict={rplan.verdicts.get(klass, VERDICT_RETAIN)}"
        )
    lines.append("")
    lines.append(f"candidates (top {top} by size):")
    for c in rplan.candidates[:top]:
        mark = "*" if c.eligible else " "
        lines.append(
            f" {mark} {_fmt(c.size_bytes):>10}  {c.klass:<18} {c.path}"
        )
        if c.reason:
            lines.append(f"                {c.reason}")
    lines.append("")
    lines.append("* = past this policy's floor. Eligibility is NOT permission -")
    lines.append("  only class verdict auto-eligible grants any, and nothing in")
    lines.append("  RC calls apply(). Deleting existing bytes is an operator call.")
    return "\n".join(lines)


def render_game_information_report(manifest: GameInformationManifest) -> str:
    """Condition (v) surface: what a termination clause would have to reach."""
    lines: list[str] = []
    lines.append(f"Game Information manifest - root {manifest.root}")
    lines.append("-" * 72)
    lines.append(
        f"total {_fmt(manifest.total_bytes)} across {len(manifest.paths)} path(s)"
    )
    for category in sorted(manifest.by_category):
        bucket = manifest.by_category[category]
        lines.append(
            f"  {category:<20} {_fmt(bucket['bytes']):>10}  n={bucket['count']}"
        )
    return "\n".join(lines)


# -- CLI (report only - there is deliberately no --apply) ----------------


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Dry-run retention report for data/. Deletes nothing.",
    )
    ap.add_argument(
        "--data-dir",
        default=str(Path(__file__).resolve().parent.parent / "data"),
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--game-information", action="store_true",
                    help="Riot terms condition (v) manifest instead of the plan.")
    ap.add_argument("--max-backup-age-days", type=int,
                    default=DEFAULT_MAX_BACKUP_AGE_DAYS)
    ap.add_argument("--max-append-log-age-days", type=int,
                    default=DEFAULT_MAX_APPEND_LOG_AGE_DAYS)
    ap.add_argument("--max-cache-gb", type=float,
                    default=DEFAULT_MAX_CACHE_BYTES / 1024**3)
    ap.add_argument("--keep-patches", type=int, default=DEFAULT_KEEP_PATCHES)
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.game_information:
        manifest = game_information_manifest(args.data_dir)
        print(json.dumps(manifest.to_dict(), indent=2) if args.json
              else render_game_information_report(manifest))
        return 0

    try:
        rplan = plan(
            args.data_dir,
            max_backup_age_days=args.max_backup_age_days,
            max_append_log_age_days=args.max_append_log_age_days,
            max_cache_bytes=int(args.max_cache_gb * 1024**3),
            keep_patches=args.keep_patches,
        )
    except ValueError as exc:
        # RM-363: a rejected policy is an operator mistake, not a crash.
        # Exit 2 keeps it distinct from exit 1, which means "the report ran
        # and something breached a floor" - a scheduled caller must be able
        # to tell a bad flag from a real finding.
        print(f"refusing this policy: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rplan.to_dict(), indent=2) if args.json
          else render_report(rplan))
    # Exit 1 when something breached a floor, so a scheduled caller notices.
    return 1 if rplan.eligible else 0


if __name__ == "__main__":
    sys.exit(main())
