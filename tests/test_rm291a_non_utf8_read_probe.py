"""RM-291 SWEEP A - the ``UnicodeDecodeError`` class, probed rather than counted.

WHY THIS FILE EXISTS
--------------------
``UnicodeDecodeError`` is a subclass of ``ValueError``. ``json.JSONDecodeError``
is a SIBLING subclass of the same ``ValueError``. Neither is an ``OSError``.
So a handler spelled ``except (OSError, json.JSONDecodeError)`` - by far the
most common shape in this repo for "read a JSON file, fail soft" - lets a
``UnicodeDecodeError`` straight through, and the enclosing function breaks the
"never raises" promise its own docstring usually makes. ``test_premise`` below
pins that relationship so the class cannot be argued away.

The class has been fixed at the root four times already (``core/polled_json.py``
in lane 8 cycle 24; ``core/augment_external_source._current_patch`` in cycle 33).
RM-291 filed a candidate POPULATION for the rest of the tree and was explicit
that the population was a hypothesis, not a defect count: "for each candidate,
write a non-UTF-8 fixture, call the enclosing function, and record RAISED or
DEGRADED - the probe is the deliverable, not the count."

This module is that probe, kept as a test so the classification is reproducible
and a regression is caught rather than re-derived.

HOW IT WORKS
------------
An ``ast`` walk over ``core/``, ``coaches/`` and ``dashboard/`` found every
``read_text`` call lexically inside a ``try`` body and collected the handler set
of every enclosing ``try``. Sites whose handler chain names ``UnicodeDecodeError``,
``ValueError``, ``Exception`` or is bare are protected; the rest are candidates.
Each candidate below gets a driver that plants REAL undecodable bytes at the path
its enclosing function actually reads, then calls that function. A driver that
returns has DEGRADED; a driver that lets ``UnicodeDecodeError`` out has RAISED.

Three candidates were kept in the table even though they degrade, because a
static scan cannot see WHY and re-deriving that costs another probe run:

  * ``core/aftergame_summary.py:425``   - an outer ``except Exception`` in the
    same function catches it (returns False, logs).
  * ``core/league_settings.py:117``     - the read passes ``errors="replace"``,
    so it cannot raise at all.
  * ``core/replay_narrative_shadow.py:101`` - outer ``except Exception``.
  * ``dashboard/routes_diag.py:116``    - BOTH ``errors="replace"`` and an outer
    ``except Exception`` at line 97.

Keeping them here is the point: they are the false-positive tier the row warned
about, and this file is the evidence that they were probed rather than assumed.

SEVERITY IS NOT UNIFORM, and the fixes note provenance per site:
  * ``data/daemon_slayer/current.txt`` and the DDragon blobs beside it are
    written by RC's own extractor, but they are also the files an operator
    hand-edits and the ones a half-finished extract truncates.
  * Four of the readers below run at IMPORT time
    (``aram_balance_context``, ``aram_tenacity_context``, ``post_game_rubric``,
    and ``daemon_slayer_resolver._derive_non_inventory_ids``, whose docstring
    says in as many words that "a throw here would take every coach down with
    it"). For those, a single bad byte is not a degraded panel, it is an
    unimportable module.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 0xFF can never begin a valid UTF-8 sequence, and 0x80 can never begin one
# either, so this is undecodable under strict UTF-8 no matter where it is cut.
BAD = b"\xff\xfe\x00\x80 not utf-8 \xff"
GOOD_PATCH = "9.9.9"


def _plant(path: Path) -> Path:
    """Write the undecodable fixture at ``path`` (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BAD)
    return path


def test_premise_unicodedecodeerror_escapes_the_common_handler():
    """The whole sweep rests on this; pin it rather than reason about it."""
    assert issubclass(UnicodeDecodeError, ValueError)
    assert not issubclass(UnicodeDecodeError, OSError)
    assert issubclass(json.JSONDecodeError, ValueError)
    # Siblings, not ancestor/descendant - which is the trap.
    assert not issubclass(UnicodeDecodeError, json.JSONDecodeError)

    escaped = False
    try:
        try:
            BAD.decode("utf-8")
        except (OSError, json.JSONDecodeError):  # the repo's common shape
            pytest.fail("unreachable: this handler cannot catch a decode error")
    except UnicodeDecodeError:
        escaped = True
    assert escaped


# --------------------------------------------------------------------------
# Drivers. Each plants BAD bytes where the enclosing function reads, then
# calls it. Raising UnicodeDecodeError = RAISED; returning = DEGRADED.
# --------------------------------------------------------------------------

def _drive_aftergame_summary(tmp_path, mp):
    m = importlib.import_module("core.aftergame_summary")
    target = _plant(tmp_path / "coaching_data.json")
    m.write_to_client_coaching_data({"mode": "client"}, target=target)


def _ds_dir_with_bad_champions(tmp_path):
    """A daemon_slayer data dir whose current.txt is fine and whose
    <patch>/champions.json is not."""
    (tmp_path / "current.txt").write_text(GOOD_PATCH, encoding="utf-8")
    _plant(tmp_path / GOOD_PATCH / "champions.json")
    return tmp_path


def _drive_aram_balance_map(tmp_path, mp):
    m = importlib.import_module("core.aram_balance_context")
    mp.setattr(m, "_DATA_DIR", _ds_dir_with_bad_champions(tmp_path))
    m._load_balance_map()


def _drive_aram_balance_grid_map(tmp_path, mp):
    m = importlib.import_module("core.aram_balance_context")
    mp.setattr(m, "_DATA_DIR", _ds_dir_with_bad_champions(tmp_path))
    m._load_balance_grid_map()


def _drive_aram_tenacity_map(tmp_path, mp):
    m = importlib.import_module("core.aram_tenacity_context")
    mp.setattr(m, "_DATA_DIR", _ds_dir_with_bad_champions(tmp_path))
    m._load_tenacity_map()


def _drive_aram_comp_verdict_patch(tmp_path, mp):
    m = importlib.import_module("core.aram_comp_verdict")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DATA_DIR", tmp_path)
    m._resolve_patch()


def _drive_aram_item_interaction_patch(tmp_path, mp):
    m = importlib.import_module("core.aram_item_interaction")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DIR", tmp_path)
    m._resolve_patch()


def _drive_arena_augment_playline_patch(tmp_path, mp):
    m = importlib.import_module("core.arena_augment_playline")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DIR", tmp_path)
    m._resolve_patch()


def _drive_auto_accept_pref(tmp_path, mp):
    m = importlib.import_module("core.auto_accept_pref")
    mp.setattr(m, "_PREF_PATH", _plant(tmp_path / "auto_accept_pref.json"))
    m.is_enabled()


def _drive_config_validator(tmp_path, mp):
    m = importlib.import_module("core.config_validator")
    m._load_json(_plant(tmp_path / "cfg.json"))


def _drive_corpus_hygiene(tmp_path, mp):
    m = importlib.import_module("core.corpus_hygiene")
    m.sidecar_has_afk(_plant(tmp_path / "sidecar.json"))


def _drive_ds_resolver_load_if_stale(tmp_path, mp):
    m = importlib.import_module("core.daemon_slayer_resolver")
    mp.setattr(m, "_INDEX_PATH", _plant(tmp_path / "items_index.json"))
    mp.setattr(m, "_cache", {})
    mp.setattr(m, "_cache_mtime", 0.0)
    m._load_if_stale()


def _drive_ds_resolver_current_patch(tmp_path, mp):
    m = importlib.import_module("core.daemon_slayer_resolver")
    mp.setattr(m, "_PATCH_FILE", _plant(tmp_path / "current.txt"))
    m._current_patch()


def _drive_ds_resolver_non_inventory(tmp_path, mp):
    m = importlib.import_module("core.daemon_slayer_resolver")
    m._derive_non_inventory_ids(_plant(tmp_path / "items.json"))


def _drive_ds_resolver_load_hp_if_stale(tmp_path, mp):
    m = importlib.import_module("core.daemon_slayer_resolver")
    (tmp_path / "current.txt").write_text(GOOD_PATCH, encoding="utf-8")
    _plant(tmp_path / GOOD_PATCH / "items.json")
    mp.setattr(m, "_DS_DATA_DIR", tmp_path)
    mp.setattr(m, "_PATCH_FILE", tmp_path / "current.txt")
    mp.setattr(m, "_hp_cache", {})
    mp.setattr(m, "_hp_cache_mtime", 0.0)
    mp.setattr(m, "_hp_cache_patch", "")
    m._load_hp_if_stale()


def _drive_decision_detector_heartbeat(tmp_path, mp):
    m = importlib.import_module("core.decision_detector")
    mp.setattr(m, "_HEARTBEAT_PATH", _plant(tmp_path / "heartbeat.json"))
    m.read_heartbeat()


def _drive_decision_detector_list_pending(tmp_path, mp):
    m = importlib.import_module("core.decision_detector")
    store = m.DecisionStore(pending_path=_plant(tmp_path / "pending.json"),
                            log_path=tmp_path / "log.jsonl")
    store.list_pending()


def _drive_item_wpa_default_items(tmp_path, mp):
    m = importlib.import_module("core.item_wpa")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DIR", tmp_path)
    m._default_items_json()


def _drive_laning_verdicts_patch(tmp_path, mp):
    m = importlib.import_module("core.laning_verdicts")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DATA_DIR", tmp_path)
    m._resolve_patch()


def _drive_league_settings(tmp_path, mp):
    m = importlib.import_module("core.league_settings")
    m.read_hud_settings(str(_plant(tmp_path / "game.cfg")))


def _drive_post_game_rubric_overrides(tmp_path, mp):
    m = importlib.import_module("core.post_game_rubric")
    mp.setattr(m, "_OVERRIDES_PATH", _plant(tmp_path / "weights.json"))
    m._load_weights_overrides()


def _drive_replay_history_champ_index(tmp_path, mp):
    m = importlib.import_module("core.replay_history")
    mp.setattr(m, "_DDR_CHAMPS", _plant(tmp_path / "ddragon_champions.json"))
    mp.setattr(m, "_id_to_champ", {})
    m._load_champ_index()


def _drive_replay_narrative_shadow(tmp_path, mp):
    m = importlib.import_module("core.replay_narrative_shadow")
    mp.setattr(m, "_LAST_SIG", {})
    m.log_replay_narrative("NA1_1", {"ok": True},
                           path=_plant(tmp_path / "shadow.jsonl"))


def _drive_riot_api_key(tmp_path, mp):
    m = importlib.import_module("core.riot_api")
    mp.setattr(m, "_API_KEY_FILE", _plant(tmp_path / "API-Key-Riot.txt"))
    mp.setattr(m, "_KEY_CACHE", None)
    mp.setattr(m, "_KEY_WARNED_MISSING", False)
    m._get_api_key()


def _drive_rofl_pull_observations(tmp_path, mp):
    m = importlib.import_module("core.rofl_archive")
    _plant(tmp_path / m._PULL_LOG)
    m.load_pull_observations(tmp_path)


def _drive_101qq_id_map(tmp_path, mp):
    m = importlib.import_module("core.smoothed_rates_101qq")
    mp.setattr(m, "_ID_MAP_PATH", _plant(tmp_path / "id_map.json"))
    mp.setattr(m, "_RECORDS_PATH", tmp_path / "records.json")
    mp.setattr(m, "_live_data_rows", lambda: None)
    m._build_snapshot()


def _drive_101qq_records(tmp_path, mp):
    m = importlib.import_module("core.smoothed_rates_101qq")
    good = tmp_path / "id_map.json"
    good.write_text(json.dumps({"1": "Annie"}), encoding="utf-8")
    mp.setattr(m, "_ID_MAP_PATH", good)
    mp.setattr(m, "_RECORDS_PATH", _plant(tmp_path / "records.json"))
    mp.setattr(m, "_live_data_rows", lambda: None)
    m._build_snapshot()


def _drive_vision_token(tmp_path, mp):
    m = importlib.import_module("core.vision_token")
    mp.delenv("RC_VISION_TOKEN", raising=False)
    mp.setattr(m, "_CONFIG_PATH", _plant(tmp_path / "vision_token.txt"))
    # The documented contract is RuntimeError with a rotation hint. Anything
    # else - including a UnicodeDecodeError - breaks every caller that catches
    # RuntimeError, so swallow only the contractual one.
    try:
        m._resolve()
    except RuntimeError:
        pass


def _drive_champ_pool_champ_index(tmp_path, mp):
    m = importlib.import_module("coaches.champ_pool_recommender")
    mp.setattr(m, "_DDR_CHAMPS", _plant(tmp_path / "ddragon_champions.json"))
    mp.setattr(m, "_name_to_id", {})
    mp.setattr(m, "_id_to_name", {})
    m._load_champ_index()


def _drive_champ_pool_materialized_kda(tmp_path, mp):
    m = importlib.import_module("coaches.champ_pool_recommender")
    mp.setattr(m, "_KDA_FILE", _plant(tmp_path / "champ_kda.json"))
    mp.setattr(m, "_kda_materialized", None)
    mp.setattr(m, "_kda_mtime", 0.0)
    m._load_materialized_kda()


class _FakeHandler:
    """Minimum surface `_serve_decisions_log` touches: `.path` and `._send`."""

    def __init__(self):
        self.path = "/api/decisions/log?limit=5"
        self.sent = []

    def _send(self, code, body, ctype):
        self.sent.append((code, body, ctype))


def _drive_routes_diag_decisions_log(tmp_path, mp):
    m = importlib.import_module("dashboard.routes_diag")
    mp.setattr(m, "_LOG_PATH", _plant(tmp_path / "decisions_log.jsonl"))
    m._serve_decisions_log(_FakeHandler())


def _drive_routes_duo_synergy_tips(tmp_path, mp):
    m = importlib.import_module("dashboard.routes_duo_synergy")
    mp.setattr(m, "_TIPS_PATH", _plant(tmp_path / "laning_tips_duo.json"))
    mp.setattr(m, "_TIPS_CACHE", None)
    m._load_tips()


def _drive_routes_pickban_counters(tmp_path, mp):
    m = importlib.import_module("dashboard.routes_pickban")
    mp.setattr(m, "_COUNTERS_PATH", _plant(tmp_path / "champion_counters.json"))
    mp.setattr(m, "_COUNTERS_INDEX", None)
    m._load_counters_index()


def _drive_deterministic_coaching_patch(tmp_path, mp):
    m = importlib.import_module("dashboard._deterministic_coaching")
    _plant(tmp_path / "current.txt")
    mp.setattr(m, "_DS_DATA", tmp_path)
    m._current_patch()


# site id -> driver. The id is `file:line` of the read_text call as found by
# the ast walk, so a reader can go straight to the source.
PROBE_SITES = {
    "core/aftergame_summary.py:425": _drive_aftergame_summary,
    "core/aram_balance_context.py:64": _drive_aram_balance_map,
    "core/aram_balance_context.py:183": _drive_aram_balance_grid_map,
    "core/aram_comp_verdict.py:86": _drive_aram_comp_verdict_patch,
    "core/aram_item_interaction.py:115": _drive_aram_item_interaction_patch,
    "core/aram_tenacity_context.py:62": _drive_aram_tenacity_map,
    "core/arena_augment_playline.py:100": _drive_arena_augment_playline_patch,
    "core/auto_accept_pref.py:44": _drive_auto_accept_pref,
    "core/config_validator.py:91": _drive_config_validator,
    "core/corpus_hygiene.py:66": _drive_corpus_hygiene,
    "core/daemon_slayer_resolver.py:93": _drive_ds_resolver_load_if_stale,
    "core/daemon_slayer_resolver.py:146": _drive_ds_resolver_current_patch,
    "core/daemon_slayer_resolver.py:217": _drive_ds_resolver_non_inventory,
    "core/daemon_slayer_resolver.py:291": _drive_ds_resolver_load_hp_if_stale,
    "core/decision_detector.py:723": _drive_decision_detector_list_pending,
    "core/decision_detector.py:1127": _drive_decision_detector_heartbeat,
    "core/item_wpa.py:84": _drive_item_wpa_default_items,
    "core/laning_verdicts.py:152": _drive_laning_verdicts_patch,
    "core/league_settings.py:117": _drive_league_settings,
    "core/post_game_rubric.py:193": _drive_post_game_rubric_overrides,
    "core/replay_history.py:78": _drive_replay_history_champ_index,
    "core/replay_narrative_shadow.py:101": _drive_replay_narrative_shadow,
    "core/riot_api.py:100": _drive_riot_api_key,
    "core/rofl_archive.py:423": _drive_rofl_pull_observations,
    "core/smoothed_rates_101qq.py:272": _drive_101qq_id_map,
    "core/smoothed_rates_101qq.py:309": _drive_101qq_records,
    "core/vision_token.py:56": _drive_vision_token,
    "coaches/champ_pool_recommender.py:62": _drive_champ_pool_champ_index,
    "coaches/champ_pool_recommender.py:157": _drive_champ_pool_materialized_kda,
    "dashboard/routes_diag.py:116": _drive_routes_diag_decisions_log,
    "dashboard/routes_duo_synergy.py:117": _drive_routes_duo_synergy_tips,
    "dashboard/routes_pickban.py:128": _drive_routes_pickban_counters,
    "dashboard/_deterministic_coaching.py:92": _drive_deterministic_coaching_patch,
}


@pytest.mark.parametrize("site", sorted(PROBE_SITES), ids=str)
def test_non_utf8_fixture_degrades_rather_than_raising(site, tmp_path, monkeypatch):
    """Plant undecodable bytes where the site reads, then call its function.

    A failure here is the RAISED classification: the handler chain at that site
    does not name UnicodeDecodeError (nor ValueError / Exception), so a single
    bad byte escapes a function whose docstring promises to fail soft.
    """
    try:
        PROBE_SITES[site](tmp_path, monkeypatch)
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"RM-291A RAISED at {site}: UnicodeDecodeError escaped the "
            f"enclosing function ({exc.__class__.__name__}: {exc}). Fix at the "
            f"read site - add UnicodeDecodeError to its handler or pass "
            f"errors= - never by widening a caller."
        )


def test_probe_covers_every_candidate_site():
    """Guard the probe itself: every driver must be wired to a distinct site."""
    assert len(PROBE_SITES) == 33
    assert len(set(PROBE_SITES.values())) == 33
    for site in PROBE_SITES:
        rel, _, line = site.rpartition(":")
        assert (ROOT / rel).is_file(), f"{rel} no longer exists"
        assert line.isdigit()
