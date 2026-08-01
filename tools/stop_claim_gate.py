"""Stop-hook claim gate - audit a finished session's claims against its own evidence.

RM-136 (CCR-127 wire + CCR-143 taxonomy, re-implemented in RC's own code; nothing
vendored). A Stop hook receives the finished transcript and nothing else, so this
is the adapter that turns a session into checkable claims. Where a claim is
explicit enough to reconcile against files and counts, `tools/truth_gate.py` is
the deeper tool; this gate is the thing that can run with no claims file at all.

Contract:
  - reads the Stop payload as JSON on stdin (measured 2026-08-01, CLI 2.1.220:
    the payload carries session_id / transcript_path / cwd / hook_event_name /
    stop_hook_active / last_assistant_message).
  - writes ops/runtime/stop_claim_report.json atomically.
  - REPORT-ONLY by default: always exit 0. `--arm` exits 2 on findings and is
    deliberately opt-in - a gate that fires wrongly once gets disabled forever,
    so arming waits until the report is observed quiet on clean sessions.

Usage (hook):
  pythonw.exe tools/stop_claim_gate.py
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "ops" / "runtime" / "stop_claim_report.json"

# Claim patterns. Deliberately narrow: a false positive costs more than a miss,
# because the first wrong flag is what gets the hook turned off.
CLAIM_TESTS_PASS = re.compile(
    r"\b(?:suite|tests?)\b[^.\n]{0,40}?\b(?:pass(?:es|ed|ing)?|green)\b"
    r"|\bgreen\b[^.\n]{0,20}?\b(?:suite|tests?)\b", re.I)
CLAIM_COUNT = re.compile(r"\b(\d[\d,]{0,9})\s+passed\b", re.I)
CLAIM_FILE = re.compile(
    r"\b(?:updated|edited|created|added|wrote|written|modified|fixed|patched)\b"
    r"[^.\n]{0,40}?([\w./\\-]+\.(?:py|md|js|css|json|html|ps1|txt|ya?ml))\b", re.I)
CLAIM_CI = re.compile(r"\bCI\b[^.\n]{0,30}?\b(?:green|passing|passed|clean)\b", re.I)
CLAIM_COMMIT = re.compile(r"\bcommitted\b|\bcommit(?:ted)?\s+(?:and pushed|is in|landed)\b", re.I)
CLAIM_PUSH = re.compile(r"\bpushed\b", re.I)
CLAIM_FULL_SUITE = re.compile(r"\b(?:full suite|all tests|entire suite|whole suite)\b", re.I)

# Evidence patterns.
EV_PYTEST = re.compile(r"(?:^|\s|-m\s)pytest\b", re.I)
EV_FILTERED = re.compile(r"\s-k\s|::|\btests?[\w/\\.-]*\.py\b", re.I)
EV_COMMIT = re.compile(r"\bgit\b[^|;&]*\bcommit\b", re.I)
EV_PUSH = re.compile(r"\bgit\b[^|;&]*\bpush\b", re.I)
EV_CI = re.compile(r"\bgh\s+(?:run|pr|api|workflow)\b|actions/runs", re.I)
EV_BYPASS = re.compile(r"--no-verify\b|--no-gpg-sign\b|core\.hooksPath\s*=", re.I)
EV_PASSED = re.compile(r"\b(\d[\d,]{0,9})\s+passed\b", re.I)
EV_VACUOUS = re.compile(r"no tests ran|collected 0 items", re.I)

EDIT_TOOLS = {"edit", "write", "multiedit", "notebookedit"}

# Everything below exists because the ARMED gate's first real session produced 9
# findings and 9 false positives (LEDGER 1154). Every one was the gate reading a
# DESCRIPTION of a thing as the thing itself: a bypass flag named inside a
# heredoc that was writing documentation, the phrase "no tests ran" appearing in
# prose, and a claim quoted as an example. Stripping quotation before matching is
# the fix; matching inside it is the bug.
_HEREDOC = re.compile(r"<<-?\s*'?(\w+)'?.*?^\1\s*$", re.S | re.M)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"", re.S)
_FENCED = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")


def strip_command_noise(command):
    """A command's heredoc body and quoted literals are DATA, not the command."""
    return _QUOTED.sub(" ", _HEREDOC.sub(" ", command))


def strip_prose_noise(text):
    """Fenced blocks, inline code and quoted spans are quotation, not assertion."""
    return _QUOTED.sub(" ", _INLINE_CODE.sub(" ", _FENCED.sub(" ", text)))
# Split on sentence boundaries only, never on the dot inside `core/ports.py` -
# a naive [.;\n] split severs every filename and silently kills check 3.
_SENTENCE = re.compile(r"(?<=[.;!?])\s+|\n")


def _blocks(row):
    message = row.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text", "")) for part in content
                        if isinstance(part, dict))
    return ""


def collect_evidence(rows):
    """Split a transcript into the assistant's claims and the session's evidence.

    Test runs are PAIRED with the result that followed them. A count or a
    "no tests ran" marker floating anywhere in the session is not an observation
    of a suite run - reading it as one is what poisoned every claim in the first
    armed session.
    """
    ev = {"texts": [], "bash": [], "edited": [], "runs": []}
    pending = None
    for row in rows:
        role = row.get("type")
        for block in _blocks(row):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and role == "assistant":
                ev["texts"].append(str(block.get("text", "")))
            elif kind == "tool_use":
                name = str(block.get("name", "")).lower()
                data = block.get("input") or {}
                if name in ("bash", "powershell"):
                    command = str(data.get("command", ""))
                    ev["bash"].append(command)
                    if EV_PYTEST.search(strip_command_noise(command)):
                        pending = {"cmd": command, "output": ""}
                        ev["runs"].append(pending)
                if name in EDIT_TOOLS:
                    target = data.get("file_path") or data.get("path") or ""
                    if target:
                        ev["edited"].append(str(target))
            elif kind == "tool_result":
                if pending is not None:
                    pending["output"] = _result_text(block)
                    pending = None
    return ev


def _sentences(texts):
    for text in texts:
        for part in _SENTENCE.split(text):
            part = part.strip()
            if part:
                yield part


def _same_file(claimed, edited_paths):
    claim = claimed.replace("\\", "/").lower().lstrip("./")
    for path in edited_paths:
        actual = path.replace("\\", "/").lower()
        if actual.endswith(claim) or claim.endswith(actual):
            return True
    return False


def audit(ev):
    """Nine checks. Every finding cites the sentence that made the claim."""
    findings = []

    def flag(check, quote, claimed="", observed=""):
        findings.append({"check": check, "quote": quote[:300],
                         "claimed": str(claimed), "observed": str(observed)})

    bash = [strip_command_noise(c) for c in ev["bash"]]
    runs = ev["runs"]
    ran_pytest = bool(runs)
    filtered_only = ran_pytest and all(EV_FILTERED.search(r["cmd"]) for r in runs)
    observed_counts = {m.replace(",", "") for r in runs
                       for m in EV_PASSED.findall(r["output"])}
    # Vacuous only if EVERY run was vacuous. One real green run answers the claim.
    vacuous = ran_pytest and all(EV_VACUOUS.search(r["output"]) for r in runs)
    did_commit = any(EV_COMMIT.search(c) for c in bash)
    did_push = any(EV_PUSH.search(c) for c in bash)
    probed_ci = any(EV_CI.search(c) for c in bash)

    # 5 - evidence-only check. Requires an actual git invocation: a bypass flag
    # NAMED in prose or a heredoc body is documentation, not a bypass.
    for command in bash:
        if EV_BYPASS.search(command) and re.search(r"\bgit\b", command):
            flag("hook_bypass", command, observed=command)

    for sentence in _sentences(strip_prose_noise(t) for t in ev["texts"]):
        claims_pass = bool(CLAIM_TESTS_PASS.search(sentence))
        if claims_pass and not ran_pytest:
            flag("tests_pass_without_run", sentence)                       # 1
        if claims_pass and vacuous:
            flag("vacuous_run", sentence, observed="no tests ran")         # 8
        if claims_pass and CLAIM_FULL_SUITE.search(sentence) and filtered_only:
            flag("full_suite_claim_over_filtered_run", sentence,           # 7
                 observed="; ".join(r["cmd"] for r in runs))
        for count in CLAIM_COUNT.findall(sentence):
            bare = count.replace(",", "")
            if observed_counts and bare not in observed_counts:
                flag("count_mismatch", sentence, claimed=bare,             # 2
                     observed=", ".join(sorted(observed_counts)))
        for path in CLAIM_FILE.findall(sentence):
            if not _same_file(path, ev["edited"]):
                flag("file_claim_without_edit", sentence, claimed=path)    # 3
        if CLAIM_CI.search(sentence) and not probed_ci:
            flag("ci_claim_without_probe", sentence)                       # 4
        if CLAIM_COMMIT.search(sentence) and not did_commit:
            flag("commit_claim_without_commit", sentence)                  # 6
        if CLAIM_PUSH.search(sentence) and not did_push:
            flag("push_claim_without_push", sentence)                      # 9
    return findings


def read_transcript(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_report(report, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--arm", action="store_true",
                        help="exit 2 on findings; OFF by default and stays off "
                             "until the report is observed quiet on clean sessions")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    report = {
        "mode": "armed" if args.arm else "report-only",
        "armed": bool(args.arm),
        "session_id": payload.get("session_id", ""),
        "cwd": payload.get("cwd", ""),
        "transcript": payload.get("transcript_path", ""),
        "findings": [],
    }

    transcript = payload.get("transcript_path")
    if not transcript or not Path(transcript).exists():
        report["error"] = "transcript-unreadable"
        write_report(report, args.report)
        return 0

    findings = audit(collect_evidence(read_transcript(transcript)))
    report["findings"] = findings

    # Exit 2 on Stop BLOCKS the session from ending and hands stderr back to the
    # model. So re-entry is the hazard: if the model restates the claim, a second
    # block loops forever. `stop_hook_active` is true once we have already
    # blocked, and it is the only thing standing between armed mode and a spin.
    reentry = bool(payload.get("stop_hook_active"))
    should_block = bool(args.arm and findings and not reentry)
    report["blocked"] = should_block
    if args.arm and findings and reentry:
        report["reason"] = "stop_hook_active"
    write_report(report, args.report)

    if should_block:
        lines = [f"stop_claim_gate: {len(findings)} claim(s) not backed by this "
                 f"session's own evidence. Fix or retract, then finish."]
        for finding in findings:
            detail = ""
            if finding["claimed"] or finding["observed"]:
                detail = f" (claimed {finding['claimed']!r} / observed {finding['observed']!r})"
            lines.append(f"  - {finding['check']}{detail}: {finding['quote']}")
        lines.append(f"  full report: {args.report}")
        # Under pythonw.exe sys.stderr can be None. Blocking with no reason is
        # worse than not blocking, so never let the emit itself raise.
        try:
            if sys.stderr is not None:
                print("\n".join(lines), file=sys.stderr)
        except (OSError, ValueError):
            pass
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
