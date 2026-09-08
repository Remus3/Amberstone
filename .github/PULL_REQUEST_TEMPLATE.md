<!-- Please read `.github/CONTRIBUTING.md` first. The honest expectation is
     stated there: this is a personal project, and a pull request may not be
     merged even when it is good. Opening an issue first usually saves you
     time. Filling this in is what makes a merge possible at all. -->

## What this changes

<!-- One item per pull request. If there are two, please send two. -->

## Why - and what you MEASURED

<!-- Not what you edited: what you observed before and after. A command and its
     output beats a description. -->

## The failing test that this makes pass

<!-- Name it: path/to/test_file.py::test_name. A behaviour change without one
     is the thing this project asks for most often and receives least. -->

## Suites run

<!-- Both, from the repository root - never `pytest .`, which deletes the live
     supervisor lock. Paste the counts you actually saw THIS run. -->

```
pytest tests
pytest agents/daemon_slayer
```

- `tests`: <!-- passed / failed / skipped -->
- `agents/daemon_slayer`: <!-- passed / failed / skipped -->

## Checklist

- [ ] I ran `python scripts/install_hooks.py` in my clone. (A fresh clone runs
      ZERO hooks - `core.hooksPath` is local config and is not cloned.)
- [ ] 7-bit ASCII only in everything I authored: no em-dashes or en-dashes, no
      smart quotes, in code, comments, docstrings, Markdown or this message.
- [ ] No `Co-Authored-By: Claude` trailer. (The hook strips it by policy, so
      its absence is deliberate.)
- [ ] I did not touch a file on the frozen list in `CLAUDE.md`, or I said
      explicitly why the change needs to.
- [ ] Nothing private is in the diff: no API keys, account identifiers, or
      absolute paths carrying a username.
