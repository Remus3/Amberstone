"""Terminal entry point + text formatters for adaptation_hint.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds `_parse_since`, the
`_format_*` renderers, `_severity_tag`, and `main`.
`coaches.adaptation_hint` re-exports these (and runs `main` under its
own `__main__` guard); bodies are byte-verbatim - behavior pinned by
the test_round* CLI suite.
"""
from __future__ import annotations

import json

from coaches._adaptation_common import SUPPORTED_MODES, _start_of_today_iso
from coaches.adaptation_hint_aggregates import kda_trends
from coaches.adaptation_hint_champion import (
    for_champion,
    format_hint_line,
    insight_card,
)
from coaches.adaptation_hint_digest import coaching_digest
from coaches.adaptation_hint_session import session_games, session_summary
from coaches.adaptation_hint_temporal import (
    day_of_week_analysis,
    duration_analysis,
    time_of_day_analysis,
)


def _parse_since(spec: str) -> str:
    """Map --since CLI values to ISO strings.

    Accepts: ``today`` (default), ``24h`` / ``48h`` / etc., ``Nh`` where
    N is a positive int, or a full ISO-8601 string (passed through).
    """
    from datetime import datetime, timedelta, timezone
    s = (spec or "today").strip().lower()
    if s in ("today", ""):
        return _start_of_today_iso()
    if s.endswith("h"):
        try:
            hours = int(s[:-1])
            return (datetime.now().astimezone() - timedelta(hours=hours)).isoformat()
        except ValueError:
            pass
    if s.endswith("d"):
        try:
            days = int(s[:-1])
            return (datetime.now().astimezone() - timedelta(days=days)).isoformat()
        except ValueError:
            pass
    # Fall through: assume ISO-8601 string the caller supplied.
    return spec


def _format_session_text(data: dict) -> str:
    lines = [f"=== Session summary since {data['since']} ==="]
    if not data["games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    wr = data["win_rate"]
    wr_str = f"{wr*100:.0f}%" if wr is not None else "-"
    lines.append(
        f"{data['games']} games | {data['wins']}W-{data['losses']}L | wr {wr_str}"
    )
    if data["avg_kda"]:
        k = data["avg_kda"]
        lines.append(
            f"avg KDA {k['ratio']} ({k['k']}/{k['d']}/{k['a']}, n={k['sample']})"
        )
    lines.append("- by mode -")
    for mode, slot in data["per_mode"].items():
        if not slot["games"]:
            continue
        kr = slot.get("kda_ratio")
        kseg = f" KDA {kr}" if kr is not None else ""
        lines.append(
            f"  {mode:<10} {slot['games']}g | {slot['wins']}W-{slot['losses']}L{kseg}"
        )
    if data["champions"]:
        lines.append("- champions -")
        for c in data["champions"]:
            wr = c.get("win_rate")
            wr_str = f"{wr*100:.0f}%" if wr is not None else "-"
            kr = c.get("kda_ratio")
            kseg = f" KDA {kr}" if kr is not None else ""
            lines.append(
                f"  {c['champion']:<18} {c['games']}g | "
                f"{c['wins']}W-{c['losses']}L | wr {wr_str}{kseg}"
            )
    return "\n".join(lines)


_SEVERITY_BAND = (
    (0.8, "!!"),
    (0.5, "!"),
    (0.0, " "),
)


def _severity_tag(sev: float) -> str:
    for floor, tag in _SEVERITY_BAND:
        if sev >= floor:
            return tag
    return " "


def _format_digest_text(data: dict) -> str:
    lines = [
        f"=== Coaching digest ({data['mode']}, {data['count']} insights) ==="
    ]
    if not data["insights"]:
        lines.append("(no actionable insights yet - play more games)")
        return "\n".join(lines)
    for ins in data["insights"]:
        tag = _severity_tag(ins["severity"])
        lines.append(
            f"  {tag} [{ins['type']:<14}] sev {ins['severity']:.2f}  {ins['message']}"
        )
    return "\n".join(lines)


def _format_duration_text(data: dict) -> str:
    scope = data.get("mode", "all")
    if data.get("champion"):
        scope = f"{data['champion']} in {scope}"
    lines = [
        f"=== Duration breakdown ({scope}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  tier       games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  - "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  -"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['tier']:<8}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['tier']} wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['tier']} wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_day_of_week_text(data: dict) -> str:
    lines = [
        f"=== Day-of-week breakdown ({data['mode']}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  day   games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  - "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  -"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['name']}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['name']} wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['name']} wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_time_of_day_text(data: dict) -> str:
    lines = [
        f"=== Time-of-day breakdown ({data['mode']}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  hr   games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  - "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  -"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['hour']:02d}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['hour']:02d}h "
            f"wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['hour']:02d}h "
            f"wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_games_text(rows: list[dict], since_spec: str = "today") -> str:
    lines = [f"=== Games since {since_spec} ({len(rows)} rows) ==="]
    if not rows:
        lines.append("(no games)")
        return "\n".join(lines)
    for r in rows:
        # Pull just the time portion for compactness when it's today.
        ts = (r["started_at"] or "")[:16].replace("T", " ")
        win = r.get("win")
        outcome = "W" if win == 1 else ("L" if win == 0 else "-")
        kda = r.get("kda")
        kda_str = (
            f"{kda['k']:>2}/{kda['d']:>2}/{kda['a']:>2}"
            if kda else "   -   "
        )
        ratio = r.get("kda_ratio")
        ratio_str = f"KDA {ratio:>4.2f}" if ratio is not None else "KDA  -  "
        dur = r.get("duration_sec") or 0
        dur_str = f"{dur // 60:>2}:{dur % 60:02d}" if dur else "  :  "
        lines.append(
            f"  {ts}  {r['mode']:<9}  {r['champion']:<16}  {outcome}  "
            f"{kda_str}  {ratio_str}  {dur_str}"
        )
    return "\n".join(lines)


def _format_trends_text(data: dict) -> str:
    """Human-readable version of kda_trends() output - for --trends."""
    lines = [f"=== {data.get('mode', '?').upper()} KDA streaks (last 10) ==="]
    hot = data.get("hot") or []
    cold = data.get("cold") or []
    if not hot and not cold:
        lines.append("(no recent-window sample yet)")
        return "\n".join(lines)
    if hot:
        lines.append("^ HOT:")
        for e in hot:
            lines.append(
                f"  {e['champion']:<18} baseline {e['baseline_ratio']:.2f}"
                f" -> recent{e['recent_ratio']:.2f}  (+{e['delta']:.2f})"
            )
    if cold:
        lines.append("v COLD:")
        for e in cold:
            lines.append(
                f"  {e['champion']:<18} baseline {e['baseline_ratio']:.2f}"
                f" -> recent{e['recent_ratio']:.2f}  ({e['delta']:+.2f})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point - see ``python -m coaches.adaptation_hint --help``."""
    import argparse
    p = argparse.ArgumentParser(
        description="Query Agent 4's adaptation aggregates from the terminal."
    )
    p.add_argument("--champion", "-c", help="Champion name (required unless --trends)")
    p.add_argument("--mode", "-m", default="aram",
                   choices=list(SUPPORTED_MODES),
                   help="Mode DB to query (default: aram)")
    p.add_argument("--enemies", "-e", default="",
                   help="Comma-separated enemy champions for matchup hints")
    p.add_argument("--format", "-f", default="hint",
                   choices=("hint", "card", "json"),
                   help="Output format (default: hint)")
    p.add_argument("--trends", action="store_true",
                   help="Dump hot/cold KDA streaks for --mode and exit")
    p.add_argument("--session", action="store_true",
                   help="Dump session summary (today's games across all modes) and exit")
    p.add_argument("--games", action="store_true",
                   help="Dump chronological game-by-game timeline and exit")
    p.add_argument("--hourly", action="store_true",
                   help="Time-of-day breakdown across --mode (or all modes) and exit")
    p.add_argument("--weekday", action="store_true",
                   help="Day-of-week breakdown across --mode (or all modes) and exit")
    p.add_argument("--duration", action="store_true",
                   help="Game-duration breakdown (stomp/quick/standard/long) and exit")
    p.add_argument("--digest", action="store_true",
                   help="Top actionable insights across all dimensions and exit")
    p.add_argument("--min-games", type=int, default=3,
                   help="Minimum games per hour bucket to qualify for best/worst (default: 3)")
    p.add_argument("--since", default="today",
                   help="Session/games since spec: today|24h|7d|<ISO> (default: today)")
    p.add_argument("--limit", type=int, default=0,
                   help="Tail-clamp for --games (default: unlimited)")
    p.add_argument("--top-n", type=int, default=3,
                   help="Top N for --trends (default: 3)")
    args = p.parse_args(argv)

    if args.trends:
        data = kda_trends(args.mode, n=args.top_n)
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_trends_text(data))
        return 0

    if args.session:
        data = session_summary(_parse_since(args.since))
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_session_text(data))
        return 0

    if args.games:
        limit = args.limit if args.limit > 0 else None
        rows = session_games(_parse_since(args.since), limit=limit)
        if args.format == "json":
            print(json.dumps(rows, indent=2))
        else:
            print(_format_games_text(rows, since_spec=args.since))
        return 0

    if args.hourly:
        # `--mode` defaults to "aram" from argparse but we treat that as
        # "all modes" here unless the user passed it explicitly; default
        # intent for a time-of-day view is cross-mode. Detect by checking
        # whether the user-supplied argv contained --mode/-m.
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = time_of_day_analysis(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_time_of_day_text(data))
        return 0

    if args.weekday:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = day_of_week_analysis(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_day_of_week_text(data))
        return 0

    if args.duration:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = duration_analysis(
            mode=(args.mode if mode_explicit else None),
            champion=args.champion or None,
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_duration_text(data))
        return 0

    if args.digest:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = coaching_digest(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            top_n=args.top_n,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_digest_text(data))
        return 0

    if not args.champion:
        p.error("--champion is required unless --trends, --session, --games, --hourly, --weekday, --duration, or --digest is given")

    enemies = [e.strip() for e in args.enemies.split(",") if e.strip()] or None

    if args.format == "hint":
        line = format_hint_line(args.champion, args.mode, enemies=enemies)
        print(line or f"(no data for {args.champion} in {args.mode})")
    elif args.format == "card":
        card = insight_card(args.champion, args.mode, enemies=enemies)
        print(card or f"(no data for {args.champion} in {args.mode})")
    else:
        data = for_champion(args.champion, args.mode)
        data["hint"] = format_hint_line(args.champion, args.mode, enemies=enemies)
        print(json.dumps(data, indent=2))
    return 0
