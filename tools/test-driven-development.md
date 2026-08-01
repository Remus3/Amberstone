---
name: test-driven-development
description: Drives development with tests. Use when implementing any logic, fixing any bug, or changing any behavior. Use when you need to prove that code works, when a bug report arrives, or when you're about to modify existing functionality.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

# Test-Driven Development

## Overview

Write a failing test before writing the code that makes it pass. For bug fixes, reproduce the bug with a test before attempting a fix. Tests are proof - "seems right" is not done. A codebase with good tests is an AI agent's superpower; a codebase without tests is a liability.

## When to Use

- Implementing any new logic or behavior
- Fixing any bug (the Prove-It Pattern)
- Modifying existing functionality
- Adding edge case handling
- Any change that could break existing behavior

**When NOT to use:** Pure configuration changes, documentation updates, or static content changes that have no behavioral impact.

**Related:** For browser-based changes, combine TDD with runtime verification using Chrome DevTools MCP - see the Browser Testing section below.

## The TDD Cycle

```
    RED                GREEN              REFACTOR
 Write a test    Write minimal code    Clean up the
 that fails  -->  to make it pass  -->  implementation  -->  (repeat)
      |                  |                    |
      v                  v                    v
   Test FAILS        Test PASSES         Tests still PASS
```

### Step 1: RED - Write a Failing Test

Write the test first. It must fail. A test that passes immediately proves nothing.

```python
# RED: This test fails because the function doesn't exist yet
def test_ds_item_dps_returns_positive_for_valid_item():
    result = compute_item_dps(item_id=3031, champion="Caitlyn", level=18)
    assert result > 0
    assert isinstance(result, float)
```

### Step 2: GREEN - Make It Pass

Write the minimum code to make the test pass. Don't over-engineer.

### Step 3: REFACTOR - Clean Up

With tests green, improve the code without changing behavior. Run tests after every refactor step.

## The Prove-It Pattern (Bug Fixes)

When a bug is reported, **do not start by trying to fix it.** Start by writing a test that reproduces it.

```
Bug report arrives
       |
       v
  Write a test that demonstrates the bug
       |
       v
  Test FAILS (confirming the bug exists)
       |
       v
  Implement the fix
       |
       v
  Test PASSES (proving the fix works)
       |
       v
  Run full test suite (no regressions)
```

## The Test Pyramid

```
          /\
         /  \         E2E Tests (~5%)
        /    \        Full user flows, real browser
       /------\
      /        \      Integration Tests (~15%)
     /          \     Component interactions, API boundaries
    /------------\
   /              \   Unit Tests (~80%)
  /                \  Pure logic, isolated, milliseconds each
 /------------------\
```

| Size | Constraints | Speed | Example |
|------|------------|-------|---------|
| **Small** | Single process, no I/O, no network | Milliseconds | Pure function tests, data transforms |
| **Medium** | Localhost only, no external services | Seconds | API tests with test DB |
| **Large** | External services allowed | Minutes | E2E, performance benchmarks |

## Writing Good Tests

### Test State, Not Interactions

Assert on the *outcome*, not on which methods were called internally.

```python
# Good: Tests what the function does (state-based)
def test_item_ranking_orders_by_dps_descending():
    items = rank_items(["Infinity Edge", "Rabadon's", "Trinity Force"], champion="Jinx")
    assert items[0].dps >= items[1].dps >= items[2].dps

# Bad: Tests how the function works internally
def test_item_ranking_calls_compute_dps():
    with patch("engine.compute_dps") as mock:
        rank_items(["Infinity Edge"], champion="Jinx")
    mock.assert_called_once()  # breaks on refactor even if behavior is unchanged
```

### DAMP Over DRY in Tests

Tests should read like specifications. Duplication is acceptable when it makes each test independently understandable.

### Prefer Real Implementations Over Mocks

```
Preference order (most to least preferred):
1. Real implementation  > Highest confidence, catches real bugs
2. Fake                 > In-memory version of a dependency
3. Stub                 > Returns canned data, no behavior
4. Mock (interaction)   > Use sparingly, only at external boundaries
```

Mock only when the real implementation is too slow, non-deterministic, or has side effects you can't control (external APIs, email, payment systems).

### Arrange-Act-Assert

```python
def test_coaching_prompt_includes_champion_name():
    # Arrange
    game_state = build_game_state(champion="Jinx", level=11)

    # Act
    prompt = build_coaching_prompt(game_state)

    # Assert
    assert "Jinx" in prompt
```

### One Assertion Per Concept

```python
# Good
def test_rejects_empty_champion_name(): ...
def test_rejects_invalid_champion_name(): ...
def test_accepts_known_champion(): ...

# Bad: everything in one test
def test_validates_champion():  # unclear what fails when it fails
    ...
```

### Name Tests Descriptively

```python
# Good: reads like a specification
class TestDaemonSlayerEngine:
    def test_returns_zero_dps_for_item_with_no_damage_stats(): ...
    def test_raises_on_unknown_champion(): ...
    def test_is_idempotent_for_same_inputs(): ...

# Bad
def test_works(): ...
def test_handles_errors(): ...
```

## Test Anti-Patterns to Avoid

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Testing implementation details | Tests break when refactoring | Test inputs and outputs |
| Flaky tests (timing, order-dependent) | Erode trust | Use deterministic assertions, isolate state |
| Mocking everything | Tests pass but production breaks | Prefer real implementations |
| No test isolation | Tests pass individually but fail together | Each test sets up/tears down its own state |
| Snapshot abuse | Large snapshots nobody reviews | Use sparingly, review every change |

## Red Flags

- Writing code without any corresponding tests
- Tests that pass on the first run (may not test what you think)
- Bug fixes without reproduction tests
- Skipping tests to make the suite pass
- Running the same test command twice in a row without any code change in between

## Verification Checklist

After completing any implementation:

- [ ] Every new behavior has a corresponding test
- [ ] All tests pass: `python -m pytest tests/ -v`
- [ ] Bug fixes include a reproduction test that failed before the fix
- [ ] Test names describe the behavior being verified
- [ ] No tests were skipped or disabled
- [ ] Coverage hasn't decreased (if tracked)

**Note:** Run each test command after a change that could affect the result. After a clean run, don't repeat the same command unless the code has changed since.
