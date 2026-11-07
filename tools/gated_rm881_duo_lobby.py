"""gated_rm881_duo_lobby.py - GATE 1 read-back: did the live lobby SEND the duo-synergy GET?

RM-881 (b) (QA23, ``a503ce413``) makes the lobby view fetch ``/api/duo-synergy``
once per party episode when the party reaches 2 in a Summoner's Rift queue
(``web/js/panels/lobby_duo_synergy.js`` ``duoSynergyQuery`` /
``createLobbyDuoSynergy``, called from ``web/js/main.js`` ``_lobbyViewRefresh``
through ``_lvDuoCtl().update(lobby)``). Its live party >= 2 read-back is owed
(docs/LIVE_GAME_GATED_SYNC.md G1-07).

WHY THE LOG AND NOT A GET (the SUBSTITUTION trap). A GET of the route from a
shell proves the route COMPUTES. The row asks whether the operator's own
dashboard SENT the request on its own. The dashboard's request trace
(``dashboard/_handler.py`` ``Handler.log_message``, DEBUG, written to the day
log because the file handler is always DEBUG) records every GET the server
saw, and ``/api/duo-synergy`` is not in ``_SUPPRESS_LOG_PATHS``. So the drain
must NOT GET the route itself inside the window; this tool reads the trace.

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md G1-07 before any lobby):
  lobby  OK iff the captured ``/api/state`` has ``lcu.phase`` Lobby (or
         Matchmaking / ReadyCheck), ``lcu.lobby.party_size`` >= 2 and
         ``lcu.lobby.queue_id`` in the SR set parsed from ``web/js/main.js``
         ``SR_QUEUE_IDS``; the expected query is then
         ``my_role=<sup if local_member first_preference is UTILITY else bot>``
         and ``top_n=4``. Else NO_RESULT (not a duo SR lobby: nothing to read).
  sent   over the trace lines inside ``--since`` .. ``--until`` (day-log clock):
         NO_RESULT iff the window holds no HTTP trace line at all (the trace
         was not captured, so silence proves nothing); FAIL iff a mock fetch
         (``/data/ui_mock/duo_synergy.json``) is seen, or no duo-synergy GET is
         seen, or a GET with the expected query answered non-200, or more GETs
         with the expected query than ``--clients`` inside any 10 s span (the
         2 s refresh re-firing: one client would log about 5); PASS iff 1 ..
         ``--clients`` GETs with the expected query, every one 200. More than
         ``--clients`` expected GETs that are NOT that close together is
         NO_RESULT: the window spans more than one party episode, a role flip
         and back, or a page reload, each of which re-fires by design - narrow
         the window to one stable episode. A GET with another query is printed,
         not graded (a role change re-fires by design).
  The day log rotates by size (``core/log_setup.py``: ``<day>.log.1`` ..
  ``.3``), so the default reads ``<day>.log`` plus every ``<day>.log.<n>``.

READ-ONLY: it reads two files; it never writes, moves, locks or deletes
anything, never GETs the route, prints no peer address, Riot id or game id,
and never ticks a row - its output is the INPUT to the evidence contract.

USAGE (from a worktree it reads the MAIN checkout's logs/ by default)
    # with a party of 2+ formed in an SR queue and the dashboard on the Lobby view:
    curl -sk https://127.0.0.1:8888/api/state > <scratch>/g107_state.json
    python tools/gated_rm881_duo_lobby.py --state <scratch>/g107_state.json \\
        --since <HH:MM:SS the party reached 2> --until <HH:MM:SS now>
Exit 0 = PASS, 1 = INCOMPLETE (a NO_RESULT check), 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_frame_readback import main_checkout  # noqa: E402

ROUTE = "/api/duo-synergy"
MOCK_URL = "/data/ui_mock/duo_synergy.json"
TOP_N = "4"
SPAM_SPAN_S = 10
LOBBY_PHASES = ("Lobby", "Matchmaking", "ReadyCheck")
_TRACE_RE = re.compile(
    r'^(\d{2}:\d{2}:\d{2})\.\d+\s+DEBUG\s+\S+\s+\[_handler\.py:\d+\]\s+\S+\s+'
    r'HTTP "(GET|POST|HEAD|PUT|DELETE|OPTIONS) (\S+) HTTP/[\d.]+" (\d{3})')
_SR_RE = re.compile(r"const\s+SR_QUEUE_IDS\s*=\s*new\s+Set\(\[([^\]]*)\]")


def sr_queue_ids(main_js: str) -> frozenset[int]:
    """The ``SR_QUEUE_IDS`` literal of web/js/main.js (comments stripped)."""
    m = _SR_RE.search(main_js)
    if not m:
        return frozenset()
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return frozenset(int(t) for t in re.findall(r"\d+", body))


def role_for_pref(pref: Any) -> str:
    """Mirror of lobby_duo_synergy.js ``roleForPref``: UTILITY -> sup, else bot."""
    return "sup" if str(pref or "").upper() == "UTILITY" else "bot"


def expected_query(state: Mapping[str, Any], sr_ids: frozenset[int]) -> tuple[dict | None, str]:
    """(expected query params, reason) for a captured ``/api/state``."""
    lcu = state.get("lcu") if isinstance(state, Mapping) else None
    if not isinstance(lcu, Mapping):
        return None, "no lcu block"
    phase = lcu.get("phase")
    if phase not in LOBBY_PHASES:
        return None, f"lcu.phase {phase!r} is not a lobby phase"
    lobby = lcu.get("lobby")
    if not isinstance(lobby, Mapping):
        return None, "no lcu.lobby"
    try:
        size = int(lobby.get("party_size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0 and isinstance(lobby.get("members"), list):
        size = len(lobby["members"])
    if size < 2:
        return None, f"party_size {size} < 2"
    if not sr_ids:
        return None, "SR_QUEUE_IDS not found in web/js/main.js"
    try:
        qid = int(lobby.get("queue_id") or 0)
    except (TypeError, ValueError):
        qid = 0
    if qid not in sr_ids:
        return None, f"queue_id {qid} is not an SR queue"
    lm = lobby.get("local_member") or {}
    prefs = lm.get("position_preferences") if isinstance(lm, Mapping) else None
    first = prefs.get("first_preference") if isinstance(prefs, Mapping) else None
    return {"my_role": role_for_pref(first), "top_n": TOP_N}, f"party {size}, queue {qid}"


def read_traces(lines: list[str], since: str, until: str) -> list[tuple[str, str, str, int]]:
    """(time, method, path, status) for each trace line inside [since, until]."""
    out = []
    for line in lines:
        m = _TRACE_RE.match(line)
        if m and since <= m.group(1) <= until:
            out.append((m.group(1), m.group(2), m.group(3), int(m.group(4))))
    return out


def grade_sent(traces: list[tuple[str, str, str, int]], want: Mapping[str, str],
               clients: int) -> tuple[str, list[str]]:
    """The ``sent`` predicate; returns (PASS | FAIL | NO_RESULT, notes)."""
    if not traces:
        return "NO_RESULT", ["no HTTP trace line in the window: the trace was not captured"]
    notes = [f"{len(traces)} HTTP trace line(s) in the window"]
    if any(path.split("?", 1)[0] == MOCK_URL for _, _, path, _ in traces):
        return "FAIL", [*notes, "a ui_mock duo_synergy.json fetch: the dashboard is in mock mode"]
    duo = [(t, path, st) for t, meth, path, st in traces
           if meth == "GET" and urlsplit(path).path == ROUTE]
    if not duo:
        return "FAIL", [*notes, "no GET /api/duo-synergy in the window"]
    hits = []
    for t, path, st in duo:
        q = {k: v[-1] for k, v in parse_qs(urlsplit(path).query).items()}
        tag = "expected" if q == dict(want) else "other-query"
        notes.append(f"{t} GET {ROUTE} my_role={q.get('my_role')} top_n={q.get('top_n')} "
                     f"-> {st} ({tag})")
        if tag == "expected":
            hits.append((t, st))
    if not hits:
        return "FAIL", [*notes, "no GET with the expected query"]
    if any(st != 200 for _, st in hits):
        return "FAIL", [*notes, "an expected GET answered non-200"]
    if len(hits) > clients:
        secs = sorted(_secs(t) for t, _ in hits)
        if any(secs[i + clients] - secs[i] <= SPAM_SPAN_S for i in range(len(secs) - clients)):
            return "FAIL", [*notes, f"more than {clients} expected GET(s) within "
                                 f"{SPAM_SPAN_S} s: the lobby refresh re-fired"]
        return "NO_RESULT", [*notes, f"{len(hits)} expected GETs > {clients} client(s), spread "
                                  "out: more than one episode or a reload; narrow the window"]
    return "PASS", [*notes, f"{len(hits)} expected GET(s), all 200"]


def _secs(hhmmss: str) -> int:
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return h * 3600 + m * 60 + s


def default_logs(day: str, base: Path | None = None) -> list[Path]:
    """``<base>/logs/<day>.log`` plus its size-rotated ``.log.<n>`` siblings, oldest first."""
    logs = (base or main_checkout() or _ROOT) / "logs"
    rotated = sorted((p for p in logs.glob(f"{day}.log.*") if p.suffix[1:].isdigit()),
                     key=lambda p: -int(p.suffix[1:]))
    return [*rotated, logs / f"{day}.log"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True, type=Path, help="captured /api/state JSON")
    ap.add_argument("--since", required=True, help="HH:MM:SS (day-log clock)")
    ap.add_argument("--until", required=True, help="HH:MM:SS (day-log clock)")
    ap.add_argument("--day", default=date.today().isoformat(), help="YYYY-MM-DD of the day log")
    ap.add_argument("--log", type=Path, default=None, help="day log (default <main>/logs/<day>.log)")
    ap.add_argument("--clients", type=int, default=1, help="open dashboard clients (default 1)")
    ap.add_argument("--main-js", type=Path, default=_ROOT / "web" / "js" / "main.js")
    a = ap.parse_args(argv)
    for hhmmss in (a.since, a.until):
        if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", hhmmss):
            ap.error(f"bad time {hhmmss!r}: want HH:MM:SS")
    try:
        state = json.loads(a.state.read_text(encoding="utf-8"))
        sr_ids = sr_queue_ids(a.main_js.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"lobby  NO_RESULT  cannot read input: {type(exc).__name__}")
        return 1
    want, why = expected_query(state, sr_ids)
    if want is None:
        print(f"lobby  NO_RESULT  {why}")
        return 1
    print(f"lobby  OK  {why}; expected my_role={want['my_role']} top_n={want['top_n']}")
    if _secs(a.until) - _secs(a.since) < SPAM_SPAN_S:
        print(f"sent   NO_RESULT  window shorter than {SPAM_SPAN_S} s: a re-firing refresh "
              "could not show")
        return 1
    lines: list[str] = []
    for log_path in ([a.log] if a.log else default_logs(a.day)):
        try:
            lines += log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            if a.log or log_path.suffix == ".log":
                print(f"sent   NO_RESULT  no day log {log_path.name}")
                return 1
        except OSError as exc:
            print(f"sent   NO_RESULT  cannot read the day log: {type(exc).__name__}")
            return 1
    verdict, notes = grade_sent(read_traces(lines, a.since, a.until), want, max(1, a.clients))
    print(f"sent   {verdict}")
    for n in notes:
        print(f"  {n}")
    return {"PASS": 0, "NO_RESULT": 1}.get(verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
