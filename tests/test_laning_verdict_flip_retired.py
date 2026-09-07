"""Pins ADR-013: the HZ-A laning-verdict flip is RETIRED.

Three kinds of assertion, deliberately:

1. STRUCTURAL (the teeth). The flip was never wired, so it cannot be retired by
   deleting a flag. It is retired by pinning the exact set of non-test,
   non-tool modules allowed to touch the precompute's VERDICT api, with SET
   EQUALITY - a subset assertion would stay green the day someone adds a served
   consumer, which is precisely the event this guard exists to catch.
2. CONTRACT. The ADR is read off disk and asserted against, rather than a
   constant in this file being asserted against itself
   (feedback_contract_test_must_read_the_contract_from_disk).
3. MATH. The mutual-information and learnability logic the decision rests on is
   exercised on synthetic samples with known answers, so the retirement is not
   resting on an unverified statistic.

ASCII only.
"""

from __future__ import annotations

import ast
import importlib.util
import math
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_ADR_PATH = _ROOT / "docs" / "adr" / "ADR-013-laning-verdict-flip-retired.md"

# The precompute module and the symbol that SERVES a verdict from it. Importing
# the module is not the offence; serving `precomputed_choices` into live coach
# output is.
_PRECOMPUTE_MODULE = "precomputed_laning_coach"
_SERVE_SYMBOL = "precomputed_choices"

# Non-test, non-tool source files permitted to reference the precompute module
# at all, each with the ONLY reason it is permitted. Adding a row here is a
# deliberate act that should cite ADR-013.
_ALLOWED_REFERENCES = {
    # Imports `laning_trigger` only - a pure string helper that renders the
    # "Caitlyn, full mana, ult up, lvl 6" condition clause. Not the verdict.
    "core/laning_verdicts.py",
    # `shadow_log_precomputed_choices` - observation only, writes
    # data/hz_choice_shadow.jsonl, has no effect on live output.
    "dashboard/_deterministic_coaching.py",
}

# Directories that are not RC application source for the purposes of this guard.
_SKIP_DIRS = {
    ".claude", ".git", "__pycache__", "tests", "tools", "scripts", "benchmarks",
    "docs", "ops", "node_modules", "data", "logs", "web", "rc-shell",
    "agents", "lib", "config", "assets", "modules",
}


def _load_tool(name: str):
    """Import a tools/ module by path (tools/ is not a package)."""
    path = _TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load_tool("replay_laning_verdict_validate")
PROBE = _load_tool("laning_verdict_information_probe")


def _app_source_files():
    """Every RC application .py under the repo root this test file lives in.

    Rooted at ``_ROOT`` rather than a hard-coded path so the guard is not
    worktree-blind, and ``_SKIP_DIRS`` is applied to the RELATIVE path so a
    worktree nested under ``.claude/`` cannot smuggle its own tree in.
    """
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.parts and rel.parts[0] in _SKIP_DIRS:
            continue
        yield rel.as_posix(), path


# ------------------------------------------------------------------- 1. structural
def _module_imports_precompute(source: str) -> bool:
    """True when ``source`` actually IMPORTS the precompute module.

    AST, not substring. Three of RC's modules name
    ``core.precomputed_laning_coach`` in a docstring while importing nothing
    from it; a substring guard calls those wiring and is then either red for a
    prose edit or quietly widened until it means nothing.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_PRECOMPUTE_MODULE in a.name for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and _PRECOMPUTE_MODULE in node.module:
                return True
            if any(_PRECOMPUTE_MODULE in a.name for a in node.names):
                return True
    return False


def test_import_detector_tells_prose_from_wiring():
    """The guard below is only as good as this predicate, so pin it directly."""
    prose = '"""Shadow-logs what core.precomputed_laning_coach would say."""\nX = 1\n'
    assert _module_imports_precompute(prose) is False
    assert _module_imports_precompute(
        "from core.precomputed_laning_coach import precomputed_choices\n") is True
    assert _module_imports_precompute(
        "from core import precomputed_laning_coach as plc\n") is True
    assert _module_imports_precompute("import core.precomputed_laning_coach\n") is True
    assert _module_imports_precompute("def f(:\n") is False  # unparseable, fail-soft


def test_precompute_has_no_served_consumer_beyond_the_allowlist():
    """SET EQUALITY on who may IMPORT the Lane A precompute.

    Red the day a served path is wired - which is the only shape the retired
    flip can come back in. Set equality, not a subset: a subset assertion stays
    green when a consumer is ADDED, which is the exact event this guard exists
    to catch.
    """
    found = set()
    for rel, path in _app_source_files():
        if _module_imports_precompute(path.read_text(encoding="utf-8", errors="replace")):
            found.add(rel)
    # The module itself is not a consumer of itself.
    found.discard(f"core/{_PRECOMPUTE_MODULE}.py")
    assert found == _ALLOWED_REFERENCES, (
        "The set of modules importing the retired Lane A laning precompute "
        f"changed. Expected {sorted(_ALLOWED_REFERENCES)}, found {sorted(found)}. "
        "If this is a NEW served consumer, ADR-013 retired that flip - re-open "
        "the ADR before adding it."
    )


def test_laning_verdicts_imports_only_the_string_helper():
    """core/laning_verdicts.py is on the LIVE served path.

    It is allowlisted above only because it imports `laning_trigger`. If it ever
    imports the verdict api, the flip is back on the served path through the
    side door.
    """
    tree = ast.parse((_ROOT / "core" / "laning_verdicts.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if _PRECOMPUTE_MODULE in node.module:
                imported.update(a.name for a in node.names)
    assert imported == {"laning_trigger"}, (
        f"core/laning_verdicts.py imports {sorted(imported)} from the retired "
        "precompute; only the pure `laning_trigger` string helper is permitted "
        "(ADR-013)."
    )


def test_serve_symbol_only_reachable_from_the_shadow_logger():
    """`precomputed_choices` may be referenced in the dashboard ONLY inside
    `shadow_log_precomputed_choices`. Anywhere else is a served path."""
    src = (_ROOT / "dashboard" / "_deterministic_coaching.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    shadow_fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "shadow_log_precomputed_choices"),
        None,
    )
    assert shadow_fn is not None, (
        "shadow_log_precomputed_choices is gone from dashboard/_deterministic_coaching.py; "
        "this guard can no longer tell shadow use from served use."
    )
    inside = {(n.lineno) for n in ast.walk(shadow_fn)
              if isinstance(n, ast.Attribute) and n.attr == _SERVE_SYMBOL}
    everywhere = {n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Attribute) and n.attr == _SERVE_SYMBOL}
    everywhere |= {n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.Name) and n.id == _SERVE_SYMBOL}
    outside = everywhere - inside
    assert not outside, (
        f"`{_SERVE_SYMBOL}` is referenced outside the shadow logger at lines "
        f"{sorted(outside)}. ADR-013 retired serving the precomputed verdict."
    )


# --------------------------------------------------------------------- 2. contract
def test_adr_013_is_on_disk_and_indexed():
    assert _ADR_PATH.exists(), f"ADR-013 missing at {_ADR_PATH}"
    index = (_ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert _ADR_PATH.name in index, "ADR-013 is not linked from docs/adr/README.md"


def test_adr_013_records_the_deciding_evidence():
    """The ADR must carry the numbers the decision rests on, not just a verdict.

    A retirement doc with no measurement in it is a doc that gets re-litigated.
    """
    text = _ADR_PATH.read_text(encoding="utf-8")
    for needle in (
        "0.48870822041553746",   # the exact reproduced SR L6 agreement
        "0.5457",                # held-out champion prior, fold A -> B
        "0.5394",                # held-out champion prior, fold B -> A
        "0.7705",                # duel winner predicts gold winner
        "-0.000262",             # Miller-Madow corrected MI at L6 - NEGATIVE
        "0.5124",                # four genuine lanes, JUNGLE dropped
        "n=1778",                # ...and its sample size
        "RM-155",
    ):
        assert needle in text, f"ADR-013 no longer records {needle!r}"


def test_adr_013_answers_the_two_objections_with_measurements_not_assertions():
    """The two claims most likely to re-open this row are "a regen would fix
    the score" and "JUNGLE proves the table is mis-built". Both were measured
    against the LIVE ENGINE rather than asserted, and the ADR must keep those
    numbers or it becomes re-openable on a stale ledger line."""
    text = _ADR_PATH.read_text(encoding="utf-8")
    for needle in (
        "LEDGER 493",     # the stale prior finding, named and dated
        "51.3 pct",       # engine solo-kill L6 - no headroom above the table
        "49.0 pct",       # engine lane gold L6
        "40.2 pct",       # engine reproduces the JUNGLE anti-correlation
        "1.2e-5",         # JUNGLE chi-square p, stated before it is disposed of
        "_stale_patch",   # the two-patch measurement condition
        "16.15.1",        # ...requested
        "16.13.1",        # ...served
    ):
        assert needle in text, f"ADR-013 no longer records {needle!r}"


def test_adr_013_carries_the_three_traps_and_the_do_not_delete_list():
    text = _ADR_PATH.read_text(encoding="utf-8")
    for needle in (
        "swaps the shipped",            # the --mode trap
        "team_position",                # why ARAM has no native measurement
        "INERT",                        # item_state
        "16.13.1",                      # the stranded-patch correction
        "hz_choice_shadow.jsonl",       # shadow logging survives
        "RC_LANING_CV_SERVED",          # explicitly NOT retired by this ADR
        "laning_scenarios",             # tables survive
    ):
        assert needle in text, f"ADR-013 no longer carries {needle!r}"


def test_gate_module_docstring_no_longer_offers_the_flip():
    """The tool's own docstring used to read '>= 0.55 with large n = a
    defensible deterministic substitute'. That sentence is an invitation to
    re-litigate on a re-run and must stay withdrawn."""
    doc = GATE.__doc__ or ""
    assert "RETIRED AS A FLIP GATE" in doc
    assert "defensible deterministic substitute" not in doc


# ------------------------------------------------- 3. the stamp rides in the artifact
def _fixture_db(path: Path) -> None:
    """One SR match, one clean lane, a 10-minute frame. Mirrors only the columns
    the reused replay_matchup_validate readers touch."""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("CREATE TABLE matches (match_id TEXT, game_mode TEXT, "
                "has_timeline INT, game_creation_ts INT)")
    cur.execute("CREATE TABLE participants (match_id TEXT, participant_id INT, "
                "team_id INT, champion_name TEXT, team_position TEXT)")
    cur.execute("CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INT, "
                "participant_id INT, total_gold REAL)")
    cur.execute("CREATE TABLE timeline_events (match_id TEXT, event_type TEXT, "
                "killer_id INT, victim_id INT, assisting_ids_json TEXT)")
    cur.execute("INSERT INTO matches VALUES ('M1','CLASSIC',1,1000)")
    cur.executemany("INSERT INTO participants VALUES (?,?,?,?,?)", [
        ("M1", 1, 100, "Garen", "TOP"),
        ("M1", 6, 200, "Darius", "TOP"),
    ])
    cur.executemany("INSERT INTO timeline_frames VALUES ('M1', ?, ?, ?)",
                    [(600000, 1, 5000.0), (600000, 6, 4000.0)])
    conn.commit()
    conn.close()


def test_every_gate_artifact_carries_the_retirement_stamp(tmp_path):
    db = tmp_path / "fix.db"
    _fixture_db(db)
    report = GATE.run_validation(
        db_path=db, levels=[6], limit=0, gold_frame_min=10,
        verdict_fn=lambda a, b, lvl: ("all_in", 0.3),
    )
    dec = report["decision"]
    assert dec["status"] == "RETIRED"
    assert dec["adr"] == "ADR-013"
    assert dec["roadmap_row"] == "RM-155"
    assert len(dec["traps"]) >= 4
    assert "swaps the shipped TABLE and never the CORPUS" in " ".join(dec["traps"])
    assert "NOT a flip gate" in report["interpretation"] or \
        "NO LONGER A FLIP GATE" in report["interpretation"]


def test_decision_stamp_is_deep_copied_not_shared(tmp_path):
    """A caller mutating one report must not poison the next one.

    The top-level key is the easy half. The NESTED `traps` list is the one that
    bites: a shallow dict() hands every report the same list object, so a single
    append rewrites the retirement record for the rest of the process.
    """
    db = tmp_path / "fix.db"
    _fixture_db(db)
    kwargs = dict(db_path=db, levels=[6], limit=0, gold_frame_min=10,
                  verdict_fn=lambda a, b, lvl: ("all_in", 0.3))
    first = GATE.run_validation(**kwargs)
    n_traps = len(first["decision"]["traps"])
    first["decision"]["status"] = "TAMPERED"
    first["decision"]["traps"].append("injected")
    second = GATE.run_validation(**kwargs)
    assert second["decision"]["status"] == "RETIRED"
    assert len(second["decision"]["traps"]) == n_traps
    assert "injected" not in second["decision"]["traps"]
    assert len(GATE._DECISION["traps"]) == n_traps, \
        "the module-level retirement constant was mutated through a report"


# ------------------------------------------------------------------------- 4. math
def test_probe_refuses_any_mode_but_sr():
    """The --mode trap inoculation. A non-sr run would score that mode's table
    against the SR corpus and hand back a plausible wrong number."""
    assert PROBE.main(["--mode", "aram"]) == 2
    assert PROBE.main(["--mode", "arena"]) == 2


def test_probe_refuses_a_missing_db(tmp_path):
    assert PROBE.main(["--db", str(tmp_path / "nope.db")]) == 2


def test_contingency_perfect_predictor_recovers_the_full_label_entropy():
    rows = [(True, True)] * 50 + [(False, False)] * 50
    out = PROBE.contingency(rows)
    assert out["agreement"] == 1.0
    assert math.isclose(out["mutual_information_bits"], out["label_entropy_bits"],
                        rel_tol=1e-9)
    assert math.isclose(out["mi_fraction_of_label_entropy"], 1.0, rel_tol=1e-9)
    assert math.isclose(out["phi"], 1.0, rel_tol=1e-9)


def test_contingency_independent_predictor_has_zero_information():
    rows = ([(True, True)] * 25 + [(True, False)] * 25
            + [(False, True)] * 25 + [(False, False)] * 25)
    out = PROBE.contingency(rows)
    assert out["agreement"] == 0.5
    assert math.isclose(out["mutual_information_bits"], 0.0, abs_tol=1e-12)
    assert math.isclose(out["phi"], 0.0, abs_tol=1e-12)


def test_contingency_inverted_predictor_carries_information_with_negative_phi():
    """A perfectly WRONG predictor is informative, not uninformative. The
    retirement claim is zero MI, not low agreement - this pins the difference."""
    rows = [(True, False)] * 50 + [(False, True)] * 50
    out = PROBE.contingency(rows)
    assert out["agreement"] == 0.0
    assert out["mutual_information_bits"] > 0.99
    assert out["phi"] < -0.99


def test_contingency_empty_sample_is_failsoft():
    assert PROBE.contingency([]) == {"n": 0}


def test_miller_madow_correction_matches_the_closed_form_for_a_full_2x2():
    """For a fully-occupied 2x2 the MI bias correction is exactly -1/(2N) nats.

    Pinned against the closed form rather than a recorded output, because this
    is the term that turns "small association" into "BELOW the noise floor" -
    the strongest sentence in ADR-013 - and a sign error would silently invert
    the claim.
    """
    rows = ([(True, True)] * 254 + [(True, False)] * 274
            + [(False, True)] * 292 + [(False, False)] * 287)   # the real L6 cells
    out = PROBE.contingency(rows)
    n = out["n"]
    assert n == 1107
    expected = -1.0 / (2 * n) / math.log(2)
    assert math.isclose(out["miller_madow_correction_bits"], expected, rel_tol=1e-12)
    assert math.isclose(out["miller_madow_correction_bits"], -0.000651617, abs_tol=1e-8)
    assert math.isclose(
        out["mutual_information_bits_miller_madow"],
        out["mutual_information_bits"] + out["miller_madow_correction_bits"],
        rel_tol=1e-12,
    )
    # The headline consequence: at this n the measured association is smaller
    # than what pure noise produces on average.
    assert out["mutual_information_bits_miller_madow"] < 0.0
    assert out["below_noise_floor"] is True


def test_miller_madow_does_not_flag_a_genuinely_informative_sample():
    """The correction must not turn every result negative - otherwise
    `below_noise_floor` would be a tautology rather than a finding."""
    rows = [(True, True)] * 500 + [(False, False)] * 500
    out = PROBE.contingency(rows)
    assert out["mutual_information_bits_miller_madow"] > 0.99
    assert out["below_noise_floor"] is False


def test_score_verdict_reports_a_jungle_excluded_pool():
    """JUNGLE pairs are the two junglers, who never lane. The charitable read
    drops them; the block must exist and must actually exclude them."""
    pairs = [PROBE._Pair("M1", "JUNGLE", "A", "B", 5000.0, 4000.0, 0, 0),
             PROBE._Pair("M1", "TOP", "C", "D", 5000.0, 4000.0, 0, 0),
             PROBE._Pair("M1", "MIDDLE", "E", "F", 4000.0, 5000.0, 0, 0)]
    out = PROBE.score_verdict(pairs, lambda a, b, lvl: ("all_in", 0.3), [6], 0.02)
    assert out["pooled_levels"]["n"] == 3
    assert out["pooled_excluding_jungle"]["n"] == 2
    assert set(out["per_role"]) == {"JUNGLE", "TOP", "MIDDLE"}


def _fold(agreement, lower_bound_clears):
    return {"beats_chance": bool(lower_bound_clears), "agreement": agreement}


def test_label_is_learnable_requires_both_held_out_folds():
    """One fold clearing 0.50 is a coin flip from noise. Requiring both is what
    makes 'the label is fine, the verdict is not' a claim instead of a hope."""
    both = {"champion_gold_prior": {"fit_a_score_b": _fold(0.55, True),
                                    "fit_b_score_a": _fold(0.54, True)}}
    one = {"champion_gold_prior": {"fit_a_score_b": _fold(0.55, True),
                                   "fit_b_score_a": _fold(0.51, False)}}
    neither = {"champion_gold_prior": {"fit_a_score_b": _fold(0.50, False),
                                       "fit_b_score_a": _fold(0.49, False)}}
    assert PROBE.label_is_learnable(both) is True
    assert PROBE.label_is_learnable(one) is False
    assert PROBE.label_is_learnable(neither) is False
    assert PROBE.label_is_learnable({}) is False


@pytest.mark.parametrize("learnable,mi_fraction,expected", [
    (True, 0.0004, "verdict_uninformative"),     # the 2026-08-06 measurement
    (False, 0.0004, "label_not_learnable"),      # the proxy rotted, not the verdict
    (True, 0.30, "verdict_carries_signal"),      # would CONTRADICT ADR-013
])
def test_probe_finding_labels_are_distinguishable(learnable, mi_fraction, expected,
                                                  monkeypatch):
    """The three findings must be reachable and distinct - a probe that can only
    ever emit `verdict_uninformative` would be a tautology, not evidence."""
    monkeypatch.setattr(PROBE, "collect_pairs", lambda *a, **k: [])
    monkeypatch.setattr(PROBE, "_load_table", lambda mode: {})
    monkeypatch.setattr(PROBE, "make_verdict_fn", lambda t: (lambda a, b, lv: (None, None)))
    monkeypatch.setattr(PROBE, "score_verdict", lambda *a, **k: {
        "pooled_levels": {"n": 10, "mi_fraction_of_label_entropy": mi_fraction},
        "per_level": {}, "per_role": {},
    })
    monkeypatch.setattr(PROBE, "learnability_control", lambda pairs: {})
    monkeypatch.setattr(PROBE, "label_is_learnable", lambda ctl: learnable)
    report = PROBE.build_report(Path("x.db"), "sr", 1, [6], 10, 0.02)
    assert report["finding"] == expected
    assert report["adr"] == "ADR-013"


def test_split_folds_partitions_by_match_never_by_pair():
    """THE leak guard. The held-out control is what turns "the verdict scored
    badly" into "the verdict carries no information", so a split that leaks is
    the one defect that would silently invalidate ADR-013.

    Up to five pairs come from one game and share a team gold state, a shared
    snowball and a shared jungler. Two pairs from the same match must therefore
    land in the SAME fold. Written against ``split_folds`` directly because a
    leak is invisible in the returned scores - both mutations it catches
    (splitting by pair, and fold_a == fold_b == everything) leave the output
    shape identical and merely inflate the number.
    """
    pairs = [PROBE._Pair(f"M{i}", lane, "Garen", "Darius", 5000.0, 4000.0, 1, 0)
             for i in range(10) for lane in ("TOP", "MIDDLE", "BOTTOM")]
    fold_a, fold_b = PROBE.split_folds(pairs)

    ids_a = {p.match_id for p in fold_a}
    ids_b = {p.match_id for p in fold_b}
    assert ids_a and ids_b, "a fold is empty - the split collapsed"
    assert not (ids_a & ids_b), (
        f"folds share match ids {sorted(ids_a & ids_b)} - the split leaks. "
        "Either it is splitting by PAIR, or both folds are the whole corpus."
    )
    assert ids_a | ids_b == {f"M{i}" for i in range(10)}
    assert len(fold_a) + len(fold_b) == len(pairs), "the split dropped pairs"
    # Every match contributed 3 pairs; each match must be wholly in one fold.
    for i in range(10):
        in_a = sum(1 for p in fold_a if p.match_id == f"M{i}")
        in_b = sum(1 for p in fold_b if p.match_id == f"M{i}")
        assert {in_a, in_b} == {0, 3}, (
            f"match M{i} was split across folds ({in_a} / {in_b}) - pair-level leak"
        )


def test_held_out_control_is_not_scored_in_sample():
    """A held-out score that equals the in-sample ceiling is a train==test leak.

    The fixture is built so the two MUST differ: the fit half has Garen ahead,
    the held-out half has Darius ahead, so a prior fitted on fold A is exactly
    wrong on fold B while the pooled in-sample prior is merely mediocre. If the
    scoring path ever leaks, these two collapse onto each other.
    """
    pairs = []
    for i in range(5):                      # fold A - Garen ahead
        pairs.append(PROBE._Pair(f"M{i}", "TOP", "Garen", "Darius",
                                 5000.0, 4000.0, 1, 0))
    for i in range(5, 10):                  # fold B - Darius ahead
        pairs.append(PROBE._Pair(f"M{i}", "TOP", "Garen", "Darius",
                                 4600.0, 5000.0, 0, 1))
    out = PROBE.learnability_control(pairs)
    prior = out["champion_gold_prior"]
    held_out = prior["fit_a_score_b"]["agreement"]
    ceiling = prior["in_sample_ceiling"]["agreement"]
    assert held_out == 0.0, (
        f"fold-A prior should be exactly wrong on fold B, got {held_out}"
    )
    assert ceiling == 0.5
    assert held_out != ceiling, (
        "the held-out score equals the in-sample ceiling - the control is "
        "scoring its own training data and the ADR-013 learnability claim is "
        "unsupported."
    )
    assert prior["fit_a_score_b"]["beats_chance"] is False


def test_learnability_control_shape_and_duel_coupling():
    pairs = [PROBE._Pair(f"M{i}", "TOP", "Garen", "Darius",
                         5000.0 + i, 4000.0, 1, 0) for i in range(10)]
    out = PROBE.learnability_control(pairs)
    assert set(out) == {"champion_gold_prior", "duel_predicts_gold"}
    # Every pair here has a duel and a gold winner on the same side.
    assert out["duel_predicts_gold"]["n"] == 10
    assert out["duel_predicts_gold"]["agreement"] == 1.0
