"""FLEET-KIT v32 (MAIN 2026-11-16 1947 ORDER to all eight, cumulative v31 + v32).

RC was at v30, so per the ORDER's section 2 it jumped straight to v32 in ONE
commit that also carries the v31 items (tests/test_fleet_kit_v31.py). v32 adds:
the status board is OPT-IN per tree (FLEET-COMMON 18; the signal is the JSON
literal `"opt_in": true` in the tracked ops/status_board.json, and RC stays
OUT), and the server-side GitHub identity guard (FLEET-COMMON 17;
`fleet_identity.py ci-check` plus the kit workflow fleet_identity_guard.yml,
copied byte for byte to .github/workflows/fleet-identity-guard.yml). These pin
the vendored bytes, the RC acts and the kit behaviour RC leans on. Every board
render here runs in tmp_path, never against the live tree. CLAUDE.md carries
the RC "KIT v32" rules line naming this guard; long form in
docs/FLEET_KIT_ADOPTION.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
WORKFLOW = ROOT / ".github" / "workflows" / "fleet-identity-guard.yml"
V32_MANIFEST_SHA256 = "cede0b7c8a80ca6ece410c07b572e4ac9dabe0bf7769d9c82d692bb1858c757d"
V32_COMMON_BLOCK_SHA256 = "0dbee15df74d42c2b50747c8194c9afd0d09c8ac7e03659515b9b3df7eca40a1"
V32_GUARD_YML_SHA256 = "262be842e373a3888295751fbeeff8f5b34a76addbd6fc3847997577d56f72ef"
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v32_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("ascii")


def _block():
    text = _text("CLAUDE.md")
    return text[text.index(BEGIN) + len(BEGIN):text.index(END)]


# ---------------------------------------------------------------- vendoring

def test_the_vendored_kit_is_the_v32_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V32_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 32 and len(man["files"]) == 25
    assert "fleet_identity_guard.yml" in man["files"]
    assert man["files"]["fleet_identity_guard.yml"] == V32_GUARD_YML_SHA256
    assert man["common_block_sha256"] == V32_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (32, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_the_common_block_is_re_embedded_with_items_17_and_18():
    block = _block()
    assert hashlib.sha256(block.encode("ascii")).hexdigest() == V32_COMMON_BLOCK_SHA256
    assert block.encode("ascii") == (KIT / "FLEET-COMMON.md").read_bytes()
    i17 = block.index("\n17. NO AI OR BOT ATTRIBUTION")
    i18 = block.index("\n18. STATUS BOARD (kit v32")
    item17, item18 = block[i17:i18], block[i18:block.index("\n19. ")]
    assert "fleet_identity_guard.yml is a required" in item17
    assert "Dependabot PRs are never merged on GitHub" in item17
    assert "OPT-IN per tree" in item18 and "ops/status_board.json" in item18
    assert '"opt_in": true' in item18 and "silent no-op (rc 0)" in item18


# ---------------------------------------------------------------- G1 workflow

def test_the_identity_guard_workflow_is_the_kit_template_byte_for_byte():
    raw = WORKFLOW.read_bytes()
    assert raw == (KIT / "fleet_identity_guard.yml").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V32_GUARD_YML_SHA256
    assert raw.count(b"\n") > 10  # positive control: real content, not an empty file
    assert b"\r\n" not in raw
    text = raw.decode("ascii")
    assert "name: fleet-identity-guard" in text and "contents: read" in text
    assert "ci-check" in text and "persist-credentials: false" in text
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch",
                              ".github/workflows/fleet-identity-guard.yml"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60,
                             check=False, creationflags=NO_WINDOW)
    assert tracked.returncode == 0, "the workflow copy must be tracked"


def _log(*rows):
    """git log text in fleet_identity.commits()'s format."""
    return "".join("\x00".join(r) + "\x1e" for r in rows)


OPERATOR = ("a" * 40, "Op Erator", "op@example.invalid", "Op Erator", "op@example.invalid",
            "feat: x\n")


def test_ci_check_passes_clean_history_and_fails_a_bot_or_ai_commit():
    ident = _load("fleet_identity")
    out = io.StringIO()
    clean = ident.ci_check("b" * 40, "HEAD", event="push", runner=lambda _a: _log(OPERATOR),
                           out=out)
    assert clean == 0, out.getvalue()
    bot = ("c" * 40, "dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com",
           "Op Erator", "op@example.invalid", "chore(deps): bump x\n")
    out = io.StringIO()
    assert ident.ci_check("b" * 40, "HEAD", runner=lambda _a: _log(OPERATOR, bot), out=out) == 1
    assert "::error::IDENTITY cccccccccc ai-or-bot-author" in out.getvalue()
    trailer = ("d" * 40, "Op Erator", "op@example.invalid", "Op Erator", "op@example.invalid",
               "fix: y\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n")
    assert ident.ci_check("b" * 40, "HEAD", runner=lambda _a: _log(trailer),
                          out=io.StringIO()) == 1


def test_ci_check_web_merge_fails_a_push_and_is_a_notice_on_a_pull_request():
    ident = _load("fleet_identity")
    web = ("e" * 40, "Op Erator", "op@example.invalid", "GitHub", "noreply@github.com",
           "Merge pull request #1\n")
    assert ident.ci_check("b" * 40, "HEAD", event="push", runner=lambda _a: _log(web),
                          out=io.StringIO()) == 1
    out = io.StringIO()
    assert ident.ci_check("b" * 40, "HEAD", event="pull_request", runner=lambda _a: _log(web),
                          out=out) == 0
    assert "::notice::IDENTITY" in out.getvalue()


def test_ci_check_fails_closed_when_it_cannot_list_commits():
    ident = _load("fleet_identity")
    assert ident.ci_check("b" * 40, "HEAD", runner=lambda _a: None, out=io.StringIO()) == 2
    assert ident.ci_check("b" * 40, "", out=io.StringIO()) == 2


# ---------------------------------------------------------------- board opt-in

def _tree(tmp_path, cfg):
    root = tmp_path / "tree"
    (root / "ops").mkdir(parents=True)
    if cfg is not None:
        (root / "ops" / "status_board.json").write_text(cfg, encoding="ascii")
    return root


def test_rc_stays_opted_out_of_the_status_board():
    """Decision recorded in docs/FLEET_KIT_ADOPTION.md (KIT v32): RC is OUT."""
    board = _load("fleet_board")
    cfg = json.loads(_text("ops/status_board.json"))
    assert cfg.get("code") == "RC"
    assert cfg.get("opt_in") is not True
    assert board.opted_in(ROOT) is False


def test_an_opted_out_tree_renders_nothing_and_writes_nothing(tmp_path):
    board = _load("fleet_board")
    for i, cfg in enumerate((None, '{"code": "RC"}\n', '{"code": "RC", "opt_in": "true"}\n',
                             '{"code": "RC", "opt_in": 1}\n', "not json\n")):
        root = _tree(tmp_path / str(i), cfg)
        assert board.opted_in(root) is False, cfg
        plan = board.render(root, 1, [], environ={})
        assert plan == {"rendered": False, "reason": "not opted in"}, cfg
        assert not (root / "ops" / "loop" / "control" / "board").exists(), cfg


def test_the_opt_in_gate_runs_before_the_headless_gate(tmp_path):
    board = _load("fleet_board")
    out = _tree(tmp_path / "out", '{"code": "RC"}\n')
    assert board.render(out, 1, [], environ={"FLEET_SUBAGENT_FIRST": "off"}) == {
        "rendered": False, "reason": "not opted in"}
    inn = _tree(tmp_path / "in", '{"code": "RC", "opt_in": true}\n')
    assert board.render(inn, 1, [], environ={"FLEET_SUBAGENT_FIRST": "off"}) == {
        "rendered": False, "reason": "headless"}
    plan = board.render(inn, 1, [], environ={})
    assert plan["rendered"] is True and plan["html"].endswith("board.html")


def test_the_cli_render_in_an_opted_out_tree_is_silent_rc_zero(tmp_path):
    root = _tree(tmp_path, '{"code": "RC"}\n')
    env = {k: v for k, v in os.environ.items()
           if k not in ("FLEET_SUBAGENT_FIRST", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS")}
    out = subprocess.run([sys.executable, str(KIT / "fleet_board.py"), "render", "--session",
                          "1", "--root", str(root)], input="not a checklist\n",
                         capture_output=True, text=True, timeout=60, check=False, env=env,
                         creationflags=NO_WINDOW)
    assert out.returncode == 0, out.stderr
    assert out.stdout == "" and out.stderr == ""
    assert not (root / "ops" / "loop" / "control" / "board").exists()


# ---------------------------------------------------------------- RC rules line

def test_claude_md_carries_the_kit_v32_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n")
                if ln.startswith("**KIT v32 (MAIN 2026-11-16 1947, cumulative)"))
    for needle in ("OPT-IN", '"opt_in": true', "RC is OUT",
                   ".github/workflows/fleet-identity-guard.yml", "fleet_identity_guard.yml",
                   "ci-check", "Guard `tests/test_fleet_kit_v32.py`"):
        assert needle in line, needle
    assert rc.index("**KIT v31 (") < rc.index("**KIT v32 (")
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
    assert "## KIT v32 (MAIN 2026-11-16 1947, cumulative)" in _text("docs/FLEET_KIT_ADOPTION.md")
