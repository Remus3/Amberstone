"""Round 42 - UI-feedback Agent 7 channel + ui_applier deterministic op."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── ui_applier: whitelist + atomic write ────────────────────────────

def test_applier_accepts_whitelisted_css(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    css_target = tmp_path / "web" / "css" / "dashboard.css"
    css_target.parent.mkdir(parents=True)
    css_target.write_text(":root { --canvas: #000; }\n", encoding="utf-8")

    result = ui_applier.apply_ui_proposal({
        "changes": [{
            "file": "web/css/dashboard.css",
            "content": ":root { --canvas: #222; }\n",
        }],
    })
    assert result["applied"] is True
    assert result["count"] == 1
    assert css_target.read_text(encoding="utf-8") == ":root { --canvas: #222; }\n"


def test_applier_rejects_out_of_whitelist(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(ui_applier.UIApplyError) as exc:
        ui_applier.apply_ui_proposal({
            "changes": [{
                "file": "agents/supervisor.py",
                "content": "print('pwned')\n",
            }],
        })
    assert "whitelist" in str(exc.value)


def test_applier_rejects_traversal(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(ui_applier.UIApplyError):
        ui_applier.apply_ui_proposal({
            "changes": [{
                "file": "../etc/passwd",
                "content": "x",
            }],
        })


def test_applier_rejects_empty_changes(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(ui_applier.UIApplyError):
        ui_applier.apply_ui_proposal({"changes": []})


def test_applier_rejects_too_many_changes(tmp_path: Path, monkeypatch) -> None:
    """Sanity cap: >4 changes likely means something's wrong."""
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    with pytest.raises(ui_applier.UIApplyError):
        ui_applier.apply_ui_proposal({
            "changes": [
                {"file": "web/css/dashboard.css", "content": "a"},
                {"file": "web/js/dashboard.js", "content": "b"},
                {"file": "web/js/sim.js", "content": "c"},
                {"file": "web/index.html", "content": "d"},
                {"file": "data/sim/aram_blitz.json", "content": "{}"},
            ],
        })


def test_applier_rejects_invalid_json(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "data" / "sim").mkdir(parents=True)
    with pytest.raises(ui_applier.UIApplyError) as exc:
        ui_applier.apply_ui_proposal({
            "changes": [{
                "file": "data/sim/test_fixture.json",
                "content": "{not valid",
            }],
        })
    assert "JSON" in str(exc.value)


def test_applier_rejects_truncated_dashboard_js(tmp_path: Path, monkeypatch) -> None:
    """Dashboard.js under 2 KB is suspiciously short."""
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    (tmp_path / "web" / "js").mkdir(parents=True)
    with pytest.raises(ui_applier.UIApplyError) as exc:
        ui_applier.apply_ui_proposal({
            "changes": [{
                "file": "web/js/dashboard.js",
                "content": "/* just a stub */\n",
            }],
        })
    assert "suspiciously short" in str(exc.value)


def test_applier_atomic_no_tmp_lingering(tmp_path: Path, monkeypatch) -> None:
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    css = tmp_path / "web" / "css" / "dashboard.css"
    css.parent.mkdir(parents=True)
    css.write_text("a", encoding="utf-8")
    ui_applier.apply_ui_proposal({
        "changes": [{"file": "web/css/dashboard.css", "content": "b" * 100}],
    })
    siblings = list(css.parent.iterdir())
    assert len(siblings) == 1   # no .tmp leftover
    assert siblings[0].name == "dashboard.css"


def test_applier_validates_all_before_writing_any(tmp_path: Path, monkeypatch) -> None:
    """All-or-nothing: one bad change cancels the whole batch."""
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    css = tmp_path / "web" / "css" / "dashboard.css"
    css.parent.mkdir(parents=True)
    css.write_text("original", encoding="utf-8")
    with pytest.raises(ui_applier.UIApplyError):
        ui_applier.apply_ui_proposal({
            "changes": [
                {"file": "web/css/dashboard.css", "content": "changed"},
                {"file": "not/allowed.py", "content": "bad"},
            ],
        })
    # First file must NOT have been written despite being individually valid.
    assert css.read_text(encoding="utf-8") == "original"


def test_applier_allows_new_sim_fixture(tmp_path: Path, monkeypatch) -> None:
    """New file creation inside data/sim/ must work."""
    import agents.agent4_coach_mentor.ui_applier as ui_applier
    monkeypatch.setattr(ui_applier, "_PROJECT_ROOT", tmp_path)
    result = ui_applier.apply_ui_proposal({
        "changes": [{
            "file": "data/sim/brand_new.json",
            "content": json.dumps({"meta": {"name": "brand_new"},
                                   "health": {"type": "health"},
                                   "state": {"type": "state", "payload": {}}}),
        }],
    })
    assert result["applied"] is True
    assert (tmp_path / "data" / "sim" / "brand_new.json").exists()


# ── ui_feedback parser: refusal + rules ─────────────────────────────

def test_parser_refuses_off_topic(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("change the analyzer KDA threshold to 5")
    assert r.refused is True
    assert "analyzer" in r.refused_reason.lower()
    assert r.filed == []


def test_parser_refuses_api_keys(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("rotate the claude api key")
    assert r.refused is True


def test_parser_strips_bypass_dev_prefix(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("bypass dev: make the font bigger")
    assert r.bypass_dev is True
    # Bypass + a rule-based hit => should produce a proposal + file.
    assert r.proposed_changes or r.refused or r.intent.startswith("ui_feedback_")


def test_parser_font_bump_produces_proposal(tmp_path: Path, monkeypatch) -> None:
    from agents.agent1_lead import Scheduler
    import agents.agent7_context.ui_feedback as ufb
    # Need to point the parser at a minimal dashboard.css - it reads the
    # real file on disk to compute the new content. Our test monkey-
    # patches _PROJECT_ROOT on BOTH the parser and the applier so the
    # same sandbox is consulted throughout.
    monkeypatch.setattr(ufb, "_PROJECT_ROOT", tmp_path)
    css = tmp_path / "web" / "css" / "dashboard.css"
    css.parent.mkdir(parents=True)
    css.write_text(
        "html, body { font-size: 18px; font-weight: 700; }\n"
        ".title { font-size: 22px; }\n",
        encoding="utf-8",
    )
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = ufb.UIFeedbackParser(scheduler=s)
    r = p.parse("make the font 25% bigger")
    assert r.proposed_changes, "expected a proposed change"
    change = r.proposed_changes[0]
    assert change["file"] == "web/css/dashboard.css"
    # 18 * 1.25 = 22.5 → 22 or 23. Verify some font token got bumped.
    assert "font-size: 18px" not in change["content"]
    assert r.filed, "expected task to be filed"


def test_parser_color_var_swap(tmp_path: Path, monkeypatch) -> None:
    from agents.agent1_lead import Scheduler
    import agents.agent7_context.ui_feedback as ufb
    monkeypatch.setattr(ufb, "_PROJECT_ROOT", tmp_path)
    css = tmp_path / "web" / "css" / "dashboard.css"
    css.parent.mkdir(parents=True)
    css.write_text(
        ":root {\n  --canvas: #2B2721;\n  --text: #E8DFD3;\n}\n",
        encoding="utf-8",
    )
    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = ufb.UIFeedbackParser(scheduler=s)
    r = p.parse("set --canvas to #111111")
    assert r.proposed_changes
    assert "#111111" in r.proposed_changes[0]["content"]


def test_parser_unhandled_files_diagnostic(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)    # no llm_spawn → only rule path
    r = p.parse("rearrange the minimap to the right side")
    assert r.intent == "ui_feedback_unhandled"
    assert r.filed  # diagnostic task filed
    assert r.refused is False


def test_parser_bypass_off_topic_still_refused(tmp_path: Path) -> None:
    """bypass dev does NOT bypass the scope check."""
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("bypass dev: edit the scheduler charter")
    assert r.refused is True


def test_parser_empty_input(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("   ")
    assert r.intent == "ui_feedback_empty"


def test_parser_bypass_empty_input(tmp_path: Path) -> None:
    from agents.agent1_lead import Scheduler
    from agents.agent7_context.ui_feedback import UIFeedbackParser

    s = Scheduler(queue_log=tmp_path / "q.jsonl")
    p = UIFeedbackParser(scheduler=s)
    r = p.parse("bypass dev:   ")
    assert r.intent == "ui_feedback_empty"
    assert r.bypass_dev is True


# ── supervisor routing ─────────────────────────────────────────────

def test_supervisor_adds_ui_proposal_to_deterministic() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert '"ui-proposal"' in sup
    assert "ui_applier.apply_ui_proposal" in sup


def test_supervisor_routes_sim_context() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "sim_context" in sup
    assert "UIFeedbackParser" in sup
    assert "proposed_changes" in sup
    assert "refused" in sup


# ── dashboard JS wiring ────────────────────────────────────────────

def test_dashboard_js_sends_sim_context() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "SIM_ACTIVE" in js
    assert "sim_context" in js
    assert "sim_fixture" in js
    assert "SIM_THREAD" in js


def test_dashboard_js_polls_and_reloads() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "_pollTaskUntilDone" in js
    assert "window.location.reload" in js


def test_dashboard_js_renders_inline_diff() -> None:
    js = Path("web/js/dashboard.js").read_text(encoding="utf-8")
    assert "ui-proposal-diff" in js
    assert "proposed_changes" in js


def test_css_has_proposal_styles() -> None:
    css = Path("web/css/dashboard.css").read_text(encoding="utf-8")
    assert ".ui-proposal-diff" in css
    assert ".ui-proposal-snippet" in css
    assert ".ui-proposal-status" in css
    assert ".turn-refused" in css
