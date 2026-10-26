"""Guard (RM-920): the DS doc's "Calibration pipeline" section is re-derived.

``docs/DAEMON_SLAYER.md`` said the log is joined against ``rewind_history.db``
"on (champion, mode, ~ts)" "after 50+ games", with "Status: accumulating".
None of that matched the code: the consumer (``core/ds_calibration_agreement.py``
driven by ``tools/ds_calibration_report.py``) joins EXACTLY on the Riot game id
(``game_id``, else a ``live_<gameId>`` ``match_key``), drops synthetic
``sess_*`` keys, and gates per (mode, scorer) cell on ``MIN_BUCKET_N``
observations - there is no games threshold. "Accumulating" was a claim about a
gitignored local file that no checkout can verify.

The section is pinned WORD FOR WORD to a template whose variable parts are
measured here: the producer callers (AST over the tracked tree, so comments and
import aliases cannot fool it), the always-written record keys (a real
``log_ds_run`` call into tmp_path), the cell gate and the report's output path.
The join claim is checked behaviourally against an in-memory database. ASCII
only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import json
import re
import sqlite3
import subprocess
from pathlib import Path

from core import ds_calibration, ds_calibration_agreement

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_REPORT_TOOL = _REPO_ROOT / "tools" / "ds_calibration_report.py"
_PRODUCER = _REPO_ROOT / "core" / "ds_calibration.py"
_AGREEMENT = _REPO_ROOT / "core" / "ds_calibration_agreement.py"
_HEADING = "## Calibration pipeline"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "agents/agent3_testing/")

_TEMPLATE = (
    "`core/ds_calibration.py` `log_ds_run` appends one line to `{log}` "
    "(gitignored) for each coaching tick whose DS dispatch returned rows. Its "
    "callers are {callers}. A line always carries {fields}; the RM-875 re-run "
    "inputs are added only when a caller passes them.\n"
    "\n"
    "`python tools/ds_calibration_report.py` runs "
    "`core/ds_calibration_agreement.py` over the log and writes `{out}`. The "
    "join with `rewind_history.db` is exact on the Riot game id: a line's "
    "`game_id`, else a `match_key` of the form `live_<gameId>`, against the "
    "numeric suffix of `matches.match_id`. It is not a (champion, mode, ~ts) "
    "match. The synthetic `sess_<mode>_<champ>_<seq>` keys minted when the game "
    "state carries no game id never join and are counted in "
    "`records_without_game_id`. One observation is one (game, item, scorer), "
    "taken at the earliest tick that recommended the item while it was unowned; "
    "a (mode, scorer) cell is reported only at `MIN_BUCKET_N` = {min_n} "
    "observations or more. There is no games threshold, and how much has "
    "accrued is a property of the local log: run the report to measure it. The "
    "result is descriptive only and never feeds `agents/daemon_slayer` rank."
)


def _section() -> str:
    text = _DOC.read_text(encoding="utf-8")
    assert text.count(_HEADING + "\n") == 1, "exactly one Calibration pipeline heading"
    body = text.split(_HEADING + "\n", 1)[1]
    body = re.split(r"\n## ", body, maxsplit=1)[0]
    return body.strip()


def _rel(path: Path) -> str:
    return Path(path).resolve().relative_to(_REPO_ROOT).as_posix()


def _join_and(items: list[str]) -> str:
    quoted = [f"`{i}`" for i in items]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " and " + quoted[-1]


def _producer_callers() -> list[str]:
    """Tracked non-test modules that import ``log_ds_run`` from core.ds_calibration."""
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=_REPO_ROOT, capture_output=True,
        text=True, check=True,
    ).stdout.splitlines()
    found = []
    for rel in tracked:
        if rel.startswith(_TEST_DIRS) or rel == "core/ds_calibration.py":
            continue
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        if "log_ds_run" not in src:
            continue
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module == "core.ds_calibration":
                if any(a.name == "log_ds_run" for a in node.names):
                    found.append(rel)
                    break
            if isinstance(node, ast.Import) and any(
                    a.name == "core.ds_calibration" for a in node.names):
                found.append(rel)
                break
    return sorted(found)


def _caller_phrase(callers: list[str]) -> str:
    # The SR coach file name does not say its mode, so the doc names it.
    parts = [f"`{c}` (SR)" if c == "coach_integration/_coach.py" else f"`{c}`"
             for c in callers]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _base_record_keys(tmp_path: Path, monkeypatch) -> list[str]:
    log = tmp_path / "ds_calibration.jsonl"
    monkeypatch.setattr(ds_calibration, "_LOG_PATH", log)
    ds_calibration.log_ds_run(champion="Ahri", mode="SR", level=1,
                              owned_items=[], ds_picks=[])
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return list(json.loads(lines[0]).keys())


def _module_path_literal(path: Path, name: str) -> str:
    """The repo-relative path a module-level ``NAME = ROOT / "a" / "b"`` names.

    Read from source because tests/conftest.py redirects the live attributes
    into tmp_path for hermeticity, so the imported value is not the default.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == name):
            consts = sorted(
                (c for c in ast.walk(node.value)
                 if isinstance(c, ast.Constant) and isinstance(c.value, str)),
                key=lambda c: (c.lineno, c.col_offset))
            return "/".join(c.value for c in consts)
    raise AssertionError(f"{name} not found in {_rel(path)}")


def _report_out() -> str:
    return _module_path_literal(_REPORT_TOOL, "DEFAULT_OUT")


def _producer_log() -> str:
    return _module_path_literal(_PRODUCER, "_LOG_PATH")


def test_producer_log_path_is_the_named_gitignored_file():
    assert _producer_log() == "data/ds_calibration.jsonl"
    assert _module_path_literal(_AGREEMENT, "DEFAULT_LOG") == "data/ds_calibration.jsonl"
    src = _PRODUCER.read_text(encoding="utf-8")
    assert '_LOG_PATH = Path(__file__).parent.parent / "data"' in src
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/ds_calibration.jsonl"], cwd=_REPO_ROOT,
    )
    assert ignored.returncode == 0, "data/ds_calibration.jsonl must stay gitignored"


def test_producer_callers_are_the_four_coaches():
    callers = _producer_callers()
    assert callers == [
        "coach_integration/_coach.py",
        "coaches/aram_coach.py",
        "coaches/arena_coach.py",
        "coaches/brawl_coach.py",
    ], callers
    sr_src = (_REPO_ROOT / "coach_integration" / "_coach.py").read_text(encoding="utf-8")
    assert re.search(r'_ds_log\(champion=champion, mode="SR"', sr_src)


def test_report_tool_runs_the_agreement_module():
    src = _REPORT_TOOL.read_text(encoding="utf-8")
    assert "from core.ds_calibration_agreement import" in src
    assert _report_out() == "data/ds_calibration_agreement.json"


def test_join_is_exact_on_game_id_not_champion_mode_ts():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, game_creation_ts INTEGER, "
        "tracked_win INTEGER, tracked_champion_id INTEGER, tracked_team_id INTEGER)"
    )
    conn.execute("INSERT INTO matches VALUES ('NA1_555', 1000000, 1, 103, 100)")
    pick = [{"item_id": "3089", "item_name": "x", "delta_dps": 1.0, "gold": 1,
             "scorer": "dps"}]
    base = {"ts": 1000.0, "champion": "Ahri", "mode": "SR", "level": 9,
            "owned_items": [], "ds_picks": pick}
    records = [
        dict(base, game_id="555", match_key="live_555"),
        dict(base, game_id="", match_key="live_777"),
        dict(base, game_id="", match_key="sess_ARAM_Ahri_1"),
        dict(base, game_id="", match_key=""),
    ]
    cov = ds_calibration_agreement.compute_ds_calibration_agreement(
        conn, records)["coverage"]
    assert cov["records"] == 4
    # The sess_* key and the keyless line share champion/mode/ts with the
    # joined match but are never matched on them.
    assert cov["records_without_game_id"] == 2
    assert cov["games_in_log"] == 2
    assert cov["games_unjoined"] == 1  # live_777: no such match


def test_cell_gate_is_min_bucket_n_observations():
    assert isinstance(ds_calibration_agreement.MIN_BUCKET_N, int)
    src = _AGREEMENT.read_text(encoding="utf-8")
    assert "if cell.n < min_n:" in src
    assert "min_n: int = MIN_BUCKET_N" in src


def test_doc_section_matches_measured_template(tmp_path, monkeypatch):
    expected = _TEMPLATE.format(
        log=_producer_log(),
        callers=_caller_phrase(_producer_callers()),
        fields=_join_and(_base_record_keys(tmp_path, monkeypatch)),
        out=_report_out(),
        min_n=ds_calibration_agreement.MIN_BUCKET_N,
    )
    assert _section() == expected


def test_doc_section_drops_the_refuted_claims():
    body = _section()
    for stale in ("50+ games", "on (champion, mode, ~ts)", "join log vs",
                  "Status: accumulating"):
        assert stale not in body, stale


def test_producer_docstring_names_the_exact_join():
    doc = ds_calibration.__doc__ or ""
    assert "approximate timestamp" not in doc
    assert "EXACTLY on the Riot game id" in doc
