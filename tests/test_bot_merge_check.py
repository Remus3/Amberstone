"""tools/bot_merge_check.py on throwaway repos: real git, the real vendored kit.

MAIN ORDER 2026-10-19-0034 DEPENDABOT-MERGE-RULE section 2.2 asks for a
post-merge check, shown to flag a synthetic bad commit in a tmp repo, never
live history. A GitHub-side merge never runs a local hook, so these commits are
made the way GitHub would write them (bot author, GitHub's web-merge
committer, a co-author trailer) and the check must catch each one after the
fact. Every repo here lives under tmp_path; nothing reads this checkout's
history or writes its control files.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from tools import bot_merge_check as bmc

_OP = ("Op Erator", "op@example.invalid")
_BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")
_WEB = ("GitHub", "noreply@github.com")


def _git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True, env=env).stdout


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path, monkeypatch):
    nohooks = tmp_path / "nohooks"
    nohooks.mkdir()
    for k, v in (("GIT_CONFIG_COUNT", "2"),
                 ("GIT_CONFIG_KEY_0", "core.hooksPath"), ("GIT_CONFIG_VALUE_0", str(nohooks)),
                 ("GIT_CONFIG_KEY_1", "commit.gpgsign"), ("GIT_CONFIG_VALUE_1", "false"),
                 ("GIT_AUTHOR_NAME", _OP[0]), ("GIT_AUTHOR_EMAIL", _OP[1]),
                 ("GIT_COMMITTER_NAME", _OP[0]), ("GIT_COMMITTER_EMAIL", _OP[1])):
        monkeypatch.setenv(k, v)


def _commit(repo, name, msg, author=_OP, committer=_OP):
    (repo / name).write_text(name + "\n", encoding="ascii")
    _git(repo, "add", name)
    env = dict(os.environ, GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
               GIT_COMMITTER_NAME=committer[0], GIT_COMMITTER_EMAIL=committer[1])
    msg_file = repo.parent / (name + ".msg")
    msg_file.write_text(msg + "\n", encoding="ascii")
    _git(repo, "commit", "-q", "-F", str(msg_file), env=env)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _git(r, "config", "--local", "fleet.operatorIdent", f"{_OP[0]} <{_OP[1]}>")
    _commit(r, "base.txt", "chore: base")
    return r


def _run(root, *argv):
    return bmc.main(["--ref", "main", "--no-fetch", *argv], root=root)


def _state(root):
    return json.loads((root / bmc.STATE_REL).read_text(encoding="ascii"))


def test_clean_operator_history_passes_and_sets_the_watermark(repo, capsys):
    tip = _commit(repo, "a.txt", "feat: operator work")
    assert _run(repo) == 0
    assert "clean" in capsys.readouterr().out
    assert _state(repo)["clean_through"] == tip


def test_a_bot_authored_commit_is_flagged(repo, capsys):
    _commit(repo, "bump.txt", "chore(deps): bump x", author=_BOT, committer=_WEB)
    assert _run(repo) == 1
    out = capsys.readouterr().out
    assert "ai-or-bot-author" in out and "web-merge-committer" in out
    assert "fleet_rewrite.py" in out
    assert not (repo / bmc.STATE_REL).exists(), "a hit must not advance the watermark"


def test_a_github_squash_with_the_operator_as_author_is_still_flagged(repo):
    """Path A's shape: operator author, but GitHub writes itself as committer
    and adds the bot as co-author by default."""
    _commit(repo, "sq.txt", "chore(deps): bump y (#20)\n\n"
            "Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>",
            committer=_WEB)
    assert _run(repo) == 1
    classes = set(bmc.class_counts(_hits(repo)))
    assert {"web-merge-committer", "co-authored-by", "trailer"} <= classes
    assert "ai-or-bot-author" not in classes


def test_any_co_author_line_is_flagged_even_a_human_one(repo, capsys):
    """The kit flags a co-author trailer only when it names an AI or a bot;
    GitHub lists every co-author as a contributor, so this check is wider."""
    _commit(repo, "co.txt", "fix: pair work\n\nCo-authored-by: Some Person <p@example.invalid>")
    assert _run(repo) == 1
    assert "co-authored-by" in capsys.readouterr().out


def test_the_watermark_limits_the_scan_to_new_commits(repo, capsys):
    _commit(repo, "old.txt", "chore: old bot commit", author=_BOT)
    assert _run(repo, "--init") == 0
    _commit(repo, "new.txt", "feat: new operator commit")
    assert _run(repo) == 0
    assert "since watermark" in capsys.readouterr().out
    _commit(repo, "late.txt", "chore: late bot commit", author=_BOT)
    before = _state(repo)["clean_through"]
    assert _run(repo) == 1
    assert _state(repo)["clean_through"] == before


def test_all_rescans_the_whole_branch_past_the_watermark(repo):
    _commit(repo, "old.txt", "chore: old bot commit", author=_BOT)
    assert _run(repo, "--init") == 0
    assert _run(repo, "--all") == 1


def test_it_fetches_a_commit_that_landed_on_the_remote(tmp_path, capsys):
    """The live shape: the bad commit is made remotely (a GitHub-side merge),
    so only a fetch can see it."""
    origin = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", "-b", "main", str(origin)], check=True)
    _commit(origin, "base.txt", "chore: base")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    _git(clone, "config", "--local", "fleet.operatorIdent", f"{_OP[0]} <{_OP[1]}>")
    assert bmc.main([], root=clone) == 0
    _commit(origin, "merged.txt", "Merge pull request #19", author=_BOT, committer=_WEB)
    assert bmc.main([], root=clone) == 1
    assert "ai-or-bot-author" in capsys.readouterr().out


def test_no_operator_set_fails_closed(tmp_path):
    r = tmp_path / "bare-config"
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    _commit(r, "a.txt", "chore: a")
    assert _run(r) == 2


def test_a_hit_is_logged_by_class_never_by_name_or_address(repo):
    _commit(repo, "bump.txt", "chore(deps): bump x", author=_BOT, committer=_WEB)
    assert _run(repo) == 1
    row = json.loads((repo / bmc.LOG_REL).read_text(encoding="ascii").splitlines()[-1])
    assert row["flagged"] == 1 and row["classes"]["ai-or-bot-author"] == 1
    text = json.dumps(row)
    for leak in (_BOT[0], _BOT[1], _WEB[1], _OP[1]):
        assert leak not in text


def _hits(root):
    kit = bmc._kit_module("fleet_identity")
    rows = kit.commits(root, ["main"])
    return bmc.classify(rows, kit.operator_idents(root), kit)
