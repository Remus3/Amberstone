"""RM-611 (X-11, external reference E): versioned PGR extractors + a golden
fixture that refuses an output change without a DERIVE_VERSION bump.

Extractors under the guard (probed 2026-10-04):
  * ``core.post_game_score.compute_match_wpa(conn, match_id, model=)`` - reads
    ``timeline_frames`` / ``timeline_events`` (the rewind schema in
    ``scripts/rewind_scraper.py``), served on demand by
    ``dashboard/routes_post_game_wpa.py`` behind an in-memory 5 min TTL.
  * ``core.pgr_event_report.render(match, timeline, pid, baselines)`` - pure
    function over Match-V5 match + timeline dicts, called on demand by
    ``tools/pgr_event_report.py``.
Neither output is persisted anywhere (no derived-row store), so
DERIVE_VERSION drives this golden test only; there are no stale rows to
re-derive.

Input path: synthetic, name-scrubbed raw documents (participant ids only, no
Riot IDs or summoner names) are written through ``core.raw_documents`` (gzip)
and read back, so the golden covers the same bytes an RM-611 re-derive would
start from.

To accept an intended change: bump the extractor's DERIVE_VERSION, then run
``python tests/test_pgr_derive_golden_rm611.py --regen`` and commit the
regenerated golden alongside the bump.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import pgr_event_report as pgr  # noqa: E402
from core import post_game_score as pgs  # noqa: E402
from core import raw_documents as rd  # noqa: E402
from scripts import rewind_scraper as rs  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "pgr_derive_golden_rm611.json"
MATCH_ID = "SYN_611"

# ----------------------------------------------------- synthetic raw docs

_POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def _raw_match() -> dict:
    return {"metadata": {"matchId": MATCH_ID},
            "info": {"gameDuration": 1500, "participants": [
                {"participantId": i, "teamId": 100 if i <= 5 else 200,
                 "teamPosition": _POS[(i - 1) % 5],
                 "win": i > 5, "timePlayed": 1500,
                 "totalMinionsKilled": 150 + i, "neutralMinionsKilled": 4,
                 "goldEarned": 9000 + 100 * i,
                 "totalDamageDealtToChampions": 15000 + 50 * i,
                 "totalDamageTaken": 14000, "visionScore": 20 + i,
                 "wardsPlaced": 9, "wardsKilled": 2, "timeCCingOthers": 11,
                 "totalHealsOnTeammates": 0, "damageDealtToTurrets": 2000,
                 "kills": 3, "deaths": 4, "assists": 6}
                for i in range(1, 11)]}}


def _pframes(minute: int) -> dict:
    out = {}
    for i in range(1, 11):
        lead = 40 * minute if i > 5 else 0
        out[str(i)] = {"participantId": i,
                       "totalGold": 500 + 380 * minute + lead + 7 * i,
                       "xp": 280 * minute + 3 * i, "level": 1 + minute // 2,
                       "currentGold": 100, "minionsKilled": 6 * minute,
                       "position": {"x": 1000 + i, "y": 1000 + i}}
    return out


def _raw_timeline() -> dict:
    ev = [
        {"type": "ITEM_PURCHASED", "timestamp": 20000, "participantId": 2,
         "itemId": 1055},
        {"type": "SKILL_LEVEL_UP", "timestamp": 61000, "participantId": 2,
         "skillSlot": 1},
        {"type": "CHAMPION_KILL", "timestamp": 185000, "killerId": 7,
         "victimId": 2, "assistingParticipantIds": [8], "bounty": 300,
         "shutdownBounty": 0, "position": {"x": 5000, "y": 5000}},
        {"type": "SKILL_LEVEL_UP", "timestamp": 190000, "participantId": 7,
         "skillSlot": 2},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 360000, "killerId": 9,
         "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON"},
        {"type": "ITEM_PURCHASED", "timestamp": 400000, "participantId": 2,
         "itemId": 3006},
        {"type": "CHAMPION_KILL", "timestamp": 545000, "killerId": 6,
         "victimId": 2, "assistingParticipantIds": [], "bounty": 274,
         "shutdownBounty": 450, "position": {"x": 6000, "y": 6000}},
        {"type": "BUILDING_KILL", "timestamp": 610000, "killerId": 8,
         "buildingType": "TOWER_BUILDING", "towerType": "OUTER_TURRET",
         "laneType": "BOT_LANE", "teamId": 100},
        {"type": "CHAMPION_KILL", "timestamp": 700000, "killerId": 2,
         "victimId": 9, "assistingParticipantIds": [1, 3], "bounty": 300,
         "shutdownBounty": 0, "position": {"x": 7000, "y": 7000}},
    ]
    frames = []
    for m in range(0, 13):
        t = m * 60000
        frames.append({"timestamp": t, "participantFrames": _pframes(m),
                       "events": [e for e in ev
                                  if t <= e["timestamp"] < t + 60000]})
    return {"metadata": {"matchId": MATCH_ID},
            "info": {"frameInterval": 60000, "frames": frames}}


def _retained_docs(tmp_dir: Path) -> tuple[dict, dict]:
    """Round-trip the raw docs through the RM-611 gzip store."""
    conn = sqlite3.connect(str(tmp_dir / "raw.db"))
    try:
        rd.ensure_schema(conn)
        rd.store(conn, MATCH_ID, "match", _raw_match())
        rd.store(conn, MATCH_ID, "timeline", _raw_timeline())
        return (rd.load(conn, MATCH_ID, "match"),
                rd.load(conn, MATCH_ID, "timeline"))
    finally:
        conn.close()


# --------------------------------------------------------- the extractors

def _wpa_output(timeline: dict) -> dict:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(rs.SCHEMA)
        for frame in timeline["info"]["frames"]:
            rs.insert_rows(conn, "timeline_frames",
                           rs.parse_frame(frame, MATCH_ID))
            rs.insert_rows(conn, "timeline_events",
                           [rs.parse_event(e, MATCH_ID)
                            for e in frame.get("events") or []])
        return pgs.compute_match_wpa(conn, MATCH_ID, model=None)
    finally:
        conn.close()


def _pgr_output(match: dict, timeline: dict) -> dict:
    return {str(pid): pgr.render(match, timeline, pid, baselines=None)
            for pid in (2, 7)}


EXTRACTORS = {
    "post_game_score": (pgs, lambda m, t: _wpa_output(t)),
    "pgr_event_report": (pgr, _pgr_output),
}


def current_outputs(tmp_dir: Path) -> dict:
    match, timeline = _retained_docs(tmp_dir)
    out = {}
    for name, (mod, fn) in EXTRACTORS.items():
        # JSON round-trip so tuples/lists and float reprs compare as stored.
        out[name] = {"derive_version": mod.DERIVE_VERSION,
                     "output": json.loads(json.dumps(fn(match, timeline)))}
    return out


# ---------------------------------------------------------------- the guard

def golden_violations(current: dict, golden: dict) -> list[str]:
    """Every way the committed golden disagrees with the extractors.

    Same version + different output -> the extractor changed without a bump.
    Different version -> the golden was not regenerated with the bump.
    """
    problems = []
    gold_ex = golden.get("extractors") or {}
    if set(gold_ex) != set(current):
        problems.append(f"extractor set drifted: golden {sorted(gold_ex)} "
                        f"vs live {sorted(current)}")
    for name, cur in current.items():
        g = gold_ex.get(name)
        if g is None:
            continue
        if cur["derive_version"] != g.get("derive_version"):
            problems.append(
                f"{name}: DERIVE_VERSION {cur['derive_version']} but golden "
                f"is v{g.get('derive_version')} - regenerate the golden "
                f"(--regen) with the bump")
        elif cur["output"] != g.get("output"):
            problems.append(
                f"{name}: output changed without a DERIVE_VERSION bump "
                f"(still v{cur['derive_version']})")
    return problems


def _load_golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ tests

def test_extractors_declare_an_int_derive_version():
    for name, (mod, _fn) in EXTRACTORS.items():
        v = getattr(mod, "DERIVE_VERSION", None)
        assert isinstance(v, int) and v >= 1, name


def test_golden_fixture_is_name_scrubbed():
    text = GOLDEN.read_text(encoding="utf-8")
    for key in ("riotIdGameName", "summonerName", "gameName", "puuid",
                "tagLine"):
        assert key not in text, key


def test_golden_is_not_vacuous(tmp_path):
    cur = current_outputs(tmp_path)
    wpa = cur["post_game_score"]["output"]
    assert wpa["ok"] is True and wpa["event_count"] >= 4
    rep = cur["pgr_event_report"]["output"]
    assert rep["2"]["view"] == "cost" and rep["2"]["lines"]
    assert rep["7"]["view"] == "decisions"


def test_extractor_output_matches_golden_for_its_version(tmp_path):
    assert golden_violations(current_outputs(tmp_path), _load_golden()) == []


def test_positive_control_changed_output_without_bump_goes_red(
        tmp_path, monkeypatch):
    # Mutate an extractor's behaviour (the fallback win-prob curve) and keep
    # DERIVE_VERSION as is: the guard MUST fire.
    real = pgs.predict_prob
    monkeypatch.setattr(pgs, "predict_prob",
                        lambda f, model=None: min(1.0, real(f, model) + 0.01))
    problems = golden_violations(current_outputs(tmp_path), _load_golden())
    assert problems == ["post_game_score: output changed without a "
                        f"DERIVE_VERSION bump (still v{pgs.DERIVE_VERSION})"]


def test_positive_control_pgr_render_change_without_bump_goes_red(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pgr, "PROMOTION_NOTE", pgr.PROMOTION_NOTE + "!")
    problems = golden_violations(current_outputs(tmp_path), _load_golden())
    assert len(problems) == 1 and problems[0].startswith(
        "pgr_event_report: output changed without")


def test_a_bump_without_regenerating_the_golden_goes_red(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pgr, "DERIVE_VERSION", pgr.DERIVE_VERSION + 1)
    problems = golden_violations(current_outputs(tmp_path), _load_golden())
    assert len(problems) == 1 and "regenerate the golden" in problems[0]


def _regen() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        cur = current_outputs(Path(d))
    payload = {"_note": ("RM-611 golden: synthetic name-scrubbed raw docs -> "
                         "PGR extractor output, keyed by DERIVE_VERSION. "
                         "Regenerate only together with a DERIVE_VERSION "
                         "bump: python tests/test_pgr_derive_golden_rm611.py "
                         "--regen"),
               "extractors": cur}
    text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    tmp = GOLDEN.with_suffix(".json.tmp")
    tmp.write_bytes(text.encode("ascii"))
    tmp.replace(GOLDEN)
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    if "--regen" in sys.argv:
        _regen()
    else:
        print(__doc__)
