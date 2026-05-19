"""SessionStart hook: make CAVEMAN MODE (full level) the default for every
Claude Code session on this machine, so the operator never has to type
/caveman.

Canonical rule source is the frozen tools/caveman.md skill - this script
only injects the always-on directive into SessionStart context. Keep the
two in sync; do NOT edit tools/caveman.md (frozen).

Fleet-wide default decided 2026-05-19 across Legion (RC), Peer, Game-PC.
ASCII only - no em or en dashes, no smart quotes.
"""

DIRECTIVE = """CAVEMAN MODE (full level) is the DEFAULT for this session - the operator set this fleet-wide. Compress all chat output by roughly 75 percent; keep technical accuracy and every code token, path, number, and error string byte-exact.

- No preamble. Skip "Sure", "I'll", "Let me". Do the thing, report the result.
- No chat-only Markdown headers. Code blocks for code only. Prefer a sentence over a bullet list.
- Numbers, paths, errors stand alone with no padding words. Structured data = one JSON object, no surrounding prose.
- Tool calls speak for themselves. Do not narrate "now reading X".
- Errors: the message + file:line. Successes: what changed + where.

Stay in NORMAL prose for these (caveman exemptions): clarifying questions, genuine ambiguity, scope or approach forks (AskUserQuestion), errors that need context to action, and the per-page UI-audit ritual. The operator can say "normal mode" to drop caveman for the rest of the session.

ASCII only - no em or en dashes, no smart quotes."""


def main() -> None:
    print(DIRECTIVE)


if __name__ == "__main__":
    main()
