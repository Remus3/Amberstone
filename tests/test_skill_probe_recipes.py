"""tests/test_skill_probe_recipes.py - Y-12 (external reference L2).

The vision relay on :8889 is plain HTTP and every frame / liveclient endpoint
is gated on an `X-RC-Token` header (`modes/shared_vision.py:25`
`_VISION_SERVER = "http://127.0.0.1:8889"`; `vision_server/_http.py` `_auth`).
Measured 2026-08-02: an https probe gets curl status 000 and an http probe
without the token gets 401 - both read exactly like a dead relay, and that
false negative once blocked a gated row (`tests/test_gated_live_probe_relay_auth.py`
pins the same fix inside `tools/gated_live_probe.py`).

Three slash-command recipes still told agents to GET https://127.0.0.1:8889/...
with no token (game-monitor, directed-headless-upgrade, headless-gated; a fourth,
headless-upgrade, was found by this guard's own enumeration). This guard keeps
them fixed.

Universe: `tools/*.md` is the TRACKED source of the slash commands;
`.claude/commands/*.md` is a gitignored byte mirror (`tools/drift_guard.py`
MIRROR_PAIRS) that a fresh clone or a worktree does not carry. Both are scanned
when present; the tracked half is anchored so an empty enumeration cannot pass.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TRACKED = _REPO / "tools"
_MIRROR = _REPO / ".claude" / "commands"

# The files the item names, plus the one the enumeration surfaced.
_ITEM_FILES = (
    "game-monitor.md",
    "directed-headless-upgrade.md",
    "headless-gated.md",
    "headless-upgrade.md",
)

_HTTPS_8889 = re.compile(r"https://(?:127\.0\.0\.1|localhost|legion-rc):8889\b",
                         re.IGNORECASE)
_PORT = re.compile(r":8889\b")
_VERB = re.compile(r"\bcurl\b|\bGET\b")
_TOKEN = "X-RC-Token"

# sha256 of the 6-line "> **SUBAGENT-FIRST" blockquote, measured at origin/main
# d1d078aab (2026-10-04). The same block is byte-identical in 20 of the 21
# command docs that carry it; the edits in this item must not touch it.
_SUBAGENT_FIRST_SHA256 = (
    "c9b8335eaf991a5e3c868b795d4c7a444e02bf8706ea0f0dbb6bf8ef00a8fb1b")

# game-monitor CONTRACT line, verbatim; Y-12 must leave it unchanged.
_GAME_MONITOR_CONTRACT = (
    "  CONTRACT: Check `https://127.0.0.1:8888/api/state` "
    "(skip cert verify; it's mkcert self-signed).")

# Symptom | Cause | Check | Fix rows: (cause keyword, memory file name).
_FAILURE_ROWS = (
    ("dead relay", "reference_vision_server_restart_does_not_redeploy"),
    ("wrong scheme", "reference_vision_relay_probe_needs_http_and_token"),
    ("missing token", "reference_vision_token_canonical"),
    ("stale frame", "feedback_capture_artifact_staleness"),
)


def recipe_violations(text: str) -> list[tuple[int, str, str]]:
    """Every bad :8889 line in one markdown body: (lineno, reason, line)."""
    out: list[tuple[int, str, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if _HTTPS_8889.search(line):
            out.append((n, "https scheme on the plain-HTTP :8889 relay", line))
        if _PORT.search(line) and _VERB.search(line) and _TOKEN not in line:
            out.append((n, ":8889 curl/GET without the X-RC-Token header", line))
    return out


def _recipe_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if _PORT.search(ln) and _VERB.search(ln)]


def _docs() -> list[Path]:
    docs = sorted(_TRACKED.glob("*.md"))
    if _MIRROR.is_dir():
        docs += sorted(_MIRROR.glob("*.md"))
    return docs


def _subagent_first_block(text: str) -> str | None:
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.startswith("> **SUBAGENT-FIRST"):
            j = i
            while j < len(lines) and lines[j].startswith(">"):
                j += 1
            return "\n".join(lines[i:j])
    return None


# -- anchor: an empty or shrunken enumeration must not pass -----------------

def test_enumeration_is_anchored():
    names = {p.name for p in sorted(_TRACKED.glob("*.md"))}
    missing = [f for f in _ITEM_FILES if f not in names]
    assert not missing, f"tracked command docs missing from the scan: {missing}"
    recipes = sum(len(_recipe_lines((_TRACKED / f).read_text(encoding="utf-8")))
                  for f in _ITEM_FILES)
    # Each item file carries at least one :8889 probe recipe line.
    assert recipes >= len(_ITEM_FILES), (
        f"only {recipes} :8889 recipe lines found in the item files - the "
        "guard would be checking nothing")


# -- the guard ------------------------------------------------------------

def test_no_command_doc_probes_8889_wrongly():
    bad = []
    for p in _docs():
        for n, why, line in recipe_violations(p.read_text(encoding="utf-8")):
            bad.append(f"{p.relative_to(_REPO).as_posix()}:{n}: {why}: {line.strip()[:120]}")
    assert not bad, (
        ":8889 is plain HTTP and token-gated; use http:// plus an X-RC-Token "
        "header resolved by core.vision_token.get_vision_token():\n"
        + "\n".join(bad))


def test_recipes_resolve_token_from_the_canonical_reader():
    """Never a literal token value - the recipe must call the resolver."""
    for f in _ITEM_FILES:
        text = (_TRACKED / f).read_text(encoding="utf-8")
        for line in _recipe_lines(text):
            assert "get_vision_token" in line or "$TOK" in line, (
                f"tools/{f}: :8889 recipe does not resolve the token via "
                f"core.vision_token: {line.strip()[:120]}")


# -- positive controls: the predicate can fail ----------------------------

def test_positive_control_planted_https_line_is_caught():
    planted = "GET `" + "https" + "://127.0.0.1:8889/latest-frame` (skip cert verify)"
    reasons = {why for _, why, _ in recipe_violations(planted)}
    assert any("https" in r for r in reasons)
    assert any("X-RC-Token" in r for r in reasons)
    for host in ("localhost", "legion-rc"):
        assert recipe_violations("see " + "https" + f"://{host}:8889/health")


def test_positive_control_tokenless_http_curl_is_caught():
    planted = "curl -s http://127.0.0.1:8889/latest-liveclient"
    assert recipe_violations(planted)
    ok = ('curl -s -H "X-RC-Token: $TOK" http://127.0.0.1:8889/latest-liveclient')
    assert recipe_violations(ok) == []


def test_prose_mention_of_the_port_is_not_a_recipe():
    assert recipe_violations("no live frame at :8889 and no desktop screenshot") == []


# -- preservation ---------------------------------------------------------

def test_subagent_first_blocks_byte_intact():
    seen = 0
    for f in _ITEM_FILES:
        blk = _subagent_first_block((_TRACKED / f).read_text(encoding="utf-8"))
        if blk is None:
            continue  # game-monitor.md carries no SUBAGENT-FIRST block
        seen += 1
        digest = hashlib.sha256(blk.encode("utf-8")).hexdigest()
        assert digest == _SUBAGENT_FIRST_SHA256, (
            f"tools/{f}: SUBAGENT-FIRST block changed (got {digest}). If the "
            "protocol block was changed ON PURPOSE in every tools/*.md that "
            "carries it, re-pin _SUBAGENT_FIRST_SHA256 to the new digest; if "
            "only this file differs, restore it to the shared block."
        )
    assert seen == 3, f"expected 3 SUBAGENT-FIRST blocks in the item files, saw {seen}"


def test_game_monitor_contract_line_unchanged():
    lines = (_TRACKED / "game-monitor.md").read_text(encoding="utf-8").splitlines()
    assert _GAME_MONITOR_CONTRACT in lines


def test_failure_tables_cite_their_memory_file():
    for f in ("game-monitor.md", "headless-gated.md"):
        text = (_TRACKED / f).read_text(encoding="utf-8")
        assert "| Symptom | Cause | Check | Fix |" in text, f"tools/{f}: no failure table"
        rows = [ln for ln in text.splitlines() if ln.startswith("|")]
        for cause, memory in _FAILURE_ROWS:
            hit = [r for r in rows if cause in r.lower()]
            assert hit, f"tools/{f}: no '{cause}' row"
            assert memory in hit[0], f"tools/{f}: '{cause}' row does not cite {memory}"
