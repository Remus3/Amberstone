"""RM-2118 - commit-message tmpfile collision and the hand-rolled note delivery.

Incident (s164, reflog `91c1dcb28` -> amend `45446f207` -> amend `268ac7c28`):
every sub-agent of ONE session shares that session's scratchpad. The O3d agent
wrote `<scratchpad>/msg.txt` at 17:06; the R1 agent chained its own
`printf ... > <scratchpad>/msg.txt` after a command the claims hook DENIED, so
its write never ran, and its `git commit -F <scratchpad>/msg.txt` (twice, plus
an amend) took O3d's message from 33 minutes earlier. The same agent delivered
its note with a one-off script and hand-appended `inbox_deliveries.jsonl`.

Guards:
1. Every RC-authored line that prescribes `git commit -F` (outside the kit's
   byte-pinned RACE GUARDS block) carries the RM-2118 rule: a unique per-agent
   tmpfile name, written fresh, read back with `git diff --cached --stat`.
2. The standard delivery path is `python ops/loop/inbox_tick.py --send <note>`
   (`send_note`): it writes atomically, re-hashes, ledgers the delivery and
   records the OutboundCap row. The CLAUDE.md carve-out names it, and no other
   RC tool writes `inbox_deliveries.jsonl`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tick_mod = _load("rc_loop_inbox_tick_rm2118", ROOT / "ops" / "loop" / "inbox_tick.py")
fi = tick_mod.fleet_inbox

# ---- 1. the commit-message tmpfile rule ------------------------------------

# The kit's RACE GUARDS line is byte-pinned (tests/test_fleet_kit_v12_race_guards.py)
# and may not carry RC prose; every other `commit -F` line must.
_PINNED_PREFIX = "> 1. Every `git commit` / `git push` runs through the tree's git lock"
_CARRIER_GLOBS = ("CLAUDE.md", ".github/CONTRIBUTING.md", "tools/*.md",
                  "ops/loop/prompts/*.md")
_WINDOW = 4  # the rule may wrap onto the next lines of the same paragraph
_MIN_SITES = 12  # measured 13 at RM-2118; an empty enumeration must not pass


def _commit_f_sites():
    sites = []
    for pattern in _CARRIER_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if "commit -F" not in line or line.startswith(_PINNED_PREFIX):
                    continue
                window = " ".join(lines[i:i + _WINDOW + 1])
                sites.append((path.relative_to(ROOT).as_posix(), i + 1, window))
    return sites


def test_the_enumeration_is_anchored():
    sites = _commit_f_sites()
    assert len(sites) >= _MIN_SITES, f"only {len(sites)} `commit -F` sites found"
    files = {f for f, _n, _w in sites}
    for must in ("CLAUDE.md", "tools/done.md", "tools/headless-queue.md",
                 "ops/loop/prompts/drain_w23_common.md"):
        assert must in files, must


def test_every_commit_f_site_carries_the_unique_tmpfile_rule():
    missing = [f"{f}:{n}" for f, n, w in _commit_f_sites() if "RM-2118" not in w]
    assert not missing, "commit -F without the RM-2118 unique-tmpfile rule: " + ", ".join(missing)


def test_claude_md_states_the_whole_rule():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("- **Commit messages:**"))
    for must in ("commitmsg-<session>-<task>.txt", "share", "git diff --cached --stat",
                 "own tool call", "RM-2118"):
        assert must in line, must


# ---- 2. the standard delivery tool ------------------------------------------

FNAME = "2026-11-14-1200-from-RC-ANSWER-to-SS-topic-TERMINAL.md"


def _roster(root: Path, dest_base: Path):
    cfg = root / tick_mod.CONFIG_REL
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"participants": {"SS": str(dest_base)}}),
                   encoding="ascii", newline="\n")
    (dest_base / tick_mod.INBOX_DIR).mkdir(parents=True)
    return dest_base / tick_mod.INBOX_DIR


def _note(tmp_path: Path, name=FNAME, body=b"# answer\n\nHOP: 2\n") -> Path:
    p = tmp_path / "scratch" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(body)
    return p


def test_send_note_writes_rehashes_ledgers_and_records_the_cap(tmp_path):
    root = tmp_path / "root"
    inbox = _roster(root, tmp_path / "sib")
    note = _note(tmp_path)
    res = tick_mod.send_note(root, note)
    assert res["reached"] == "1/1" and res["to"] == "SS" and res["cls"] == "ANSWER"
    sent = inbox / FNAME
    assert sent.read_bytes() == note.read_bytes()
    row = json.loads((root / tick_mod.DELIVERIES_REL).read_text(encoding="ascii"))
    assert row["sha256"] == hashlib.sha256(sent.read_bytes()).hexdigest()
    assert row["reached"] == "1/1" and row["note"] == FNAME
    cap_rows = (root / fi.OUTBOUND_REL).read_text(encoding="ascii").splitlines()
    assert json.loads(cap_rows[-1])["note"] == FNAME


def test_send_note_to_main_uses_the_agreement_inbox(tmp_path):
    root = tmp_path / "root"
    main_inbox = tmp_path / "main_inbox"
    main_inbox.mkdir()
    agr = root / tick_mod.AGREEMENT_REL
    agr.parent.mkdir(parents=True)
    agr.write_text(json.dumps({"main": {"code": "MAIN", "inbox": str(main_inbox)}}),
                   encoding="ascii", newline="\n")
    name = "2026-11-14-1200-from-RC-ANSWER-to-MAIN-x-TERMINAL.md"
    res = tick_mod.send_note(root, _note(tmp_path, name))
    assert res["reached"] == "1/1"
    assert (main_inbox / name).is_file()


@pytest.mark.parametrize("body", [b"caf\xc3\xa9\n", b"a\r\nb\r\n"])
def test_send_note_refuses_non_ascii_or_crlf(tmp_path, body):
    root = tmp_path / "root"
    _roster(root, tmp_path / "sib")
    with pytest.raises(ValueError):
        tick_mod.send_note(root, _note(tmp_path, body=body))
    assert not (root / tick_mod.DELIVERIES_REL).exists()


def test_send_note_refuses_a_name_that_is_not_an_rc_note(tmp_path):
    root = tmp_path / "root"
    _roster(root, tmp_path / "sib")
    with pytest.raises(ValueError):
        tick_mod.send_note(root, _note(tmp_path, "note.md"))


def test_send_note_holds_when_the_outbound_cap_is_spent(tmp_path):
    root = tmp_path / "root"
    inbox = _roster(root, tmp_path / "sib")
    cap = fi.OutboundCap(root)
    for i in range(fi.OUTBOUND_CAP):
        cap.record(f"n{i}.md", "ANSWER", "CS")
    res = tick_mod.send_note(root, _note(tmp_path))
    assert res["reached"] == "0/1" and res["held"] == "outbound_cap"
    assert not (inbox / FNAME).exists()


def test_send_note_unmapped_destination_reaches_nothing(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    res = tick_mod.send_note(root, _note(tmp_path))
    assert res["reached"] == "0/1"
    assert not (root / fi.OUTBOUND_REL).exists()


def test_the_cli_exposes_send(tmp_path, capsys):
    root = tmp_path / "root"
    _roster(root, tmp_path / "sib")
    rc = tick_mod.main(["--root", str(root), "--send", str(_note(tmp_path))])
    assert rc == 0
    assert json.loads(capsys.readouterr().out.strip())["reached"] == "1/1"


def test_claude_md_carve_out_names_the_standard_tool():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if x.startswith("- **ONE carve-out:**"))
    assert "ops/loop/inbox_tick.py --send" in line
    assert "inbox_deliveries.jsonl" in line and "RM-2118" in line


def test_no_other_rc_tool_writes_the_delivery_ledger():
    hits = []
    for base in ("tools", "ops/loop", "core", "dashboard", "app"):
        for p in sorted((ROOT / base).rglob("*.py")):
            if "inbox_deliveries" in p.read_text(encoding="utf-8", errors="replace"):
                hits.append(p.relative_to(ROOT).as_posix())
    assert hits == ["ops/loop/inbox_tick.py"], hits


def test_the_carve_out_line_is_unique_and_ascii():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(re.findall(r"^- \*\*ONE carve-out:\*\*", text, re.M)) == 1
    text.encode("ascii")
