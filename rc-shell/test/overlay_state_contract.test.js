// rc-shell/test/overlay_state_contract.test.js
//
// Contract test: docs/ELECTRON_OVERLAY.md section 5 "Window state machine" ships
// a phase -> (companion, overlay, interaction) table. Nothing pinned that table
// to src/overlay_state.js, so the doc and the implementation could drift apart in
// either direction and no test would notice.
//
// This test therefore PARSES THE TABLE OFF DISK and derives every expectation
// from the parsed cells. Restating the same expectations as literals here would
// be a tautology that pins nothing (memory
// feedback_contract_test_must_read_the_contract_from_disk): editing the doc alone
// has to be able to turn this suite red.
//
// The test supplies only the GIVEN side as literals - one /api/state-shaped
// fixture per doc phase label, because "champ-select" is a human phrase the shell
// never sees (it reads no LCU phase at all; the gate is the liveclient object).
// The EXPECTED side is entirely doc-derived.

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const ov = require("../src/overlay_state");

const DOC_PATH = path.join(__dirname, "..", "..", "docs", "ELECTRON_OVERLAY.md");

// --- doc parsing --------------------------------------------------------------

// Canonical cell tokens -> the windowActions verb the implementation returns.
// An unmapped token is a hard parse error, never a silent skip: a doc edit to an
// unmodelled word must fail loudly rather than quietly stop asserting anything.
const WINDOW_TOKENS = Object.freeze({
  show: "show",
  hidden: "hide",
  hide: "hide",
});

const INTERACTION_TOKENS = Object.freeze(["-", "passive", "active"]);

// Pull the section-5 fenced block, then the fixed-width rows inside it. Anchored
// on the section heading + the column header so a fence added elsewhere in the
// doc can never be mistaken for the contract.
function parseContract(text) {
  const secStart = text.indexOf("## 5. Window state machine");
  assert.notStrictEqual(secStart, -1, "section 5 heading missing from the doc");
  const secEnd = text.indexOf("\n## ", secStart + 1);
  const section = text.slice(secStart, secEnd === -1 ? undefined : secEnd);

  const fenceOpen = section.indexOf("```");
  assert.notStrictEqual(fenceOpen, -1, "section 5 has no fenced contract block");
  const bodyStart = section.indexOf("\n", fenceOpen) + 1;
  const fenceClose = section.indexOf("```", bodyStart);
  assert.notStrictEqual(fenceClose, -1, "section 5 contract block is unterminated");
  const lines = section.slice(bodyStart, fenceClose).split("\n");

  const header = lines[0];
  assert.match(header, /^phase\/mode_key\s+companion\s+overlay\s+interaction\s*$/);
  assert.match(lines[1], /^-+\s+-+\s+-+\s+-+\s*$/);

  const rows = [];
  let modeSet = null;
  for (const raw of lines.slice(2)) {
    const line = raw.trimEnd();
    if (line.trim() === "") {
      continue;
    }
    const setMatch = /^game mode_key set:\s*\{([^}]*)\}$/.exec(line.trim());
    if (setMatch) {
      modeSet = setMatch[1]
        .split(",")
        .map((m) => m.trim())
        .filter((m) => m !== "");
      continue;
    }
    const cells = line.split(/\s{2,}/).map((c) => c.trim());
    assert.strictEqual(
      cells.length,
      4,
      `contract row is not 4 columns: ${JSON.stringify(line)}`
    );
    const [phase, companion, overlay, interaction] = cells;
    const companionVerb = WINDOW_TOKENS[companion];
    const overlayVerb = WINDOW_TOKENS[overlay];
    assert.ok(companionVerb, `unmodelled companion token ${JSON.stringify(companion)}`);
    assert.ok(overlayVerb, `unmodelled overlay token ${JSON.stringify(overlay)}`);
    assert.ok(
      INTERACTION_TOKENS.includes(interaction),
      `unmodelled interaction token ${JSON.stringify(interaction)}`
    );
    rows.push({ phase, companion: companionVerb, overlay: overlayVerb, interaction });
  }
  assert.ok(modeSet && modeSet.length > 0, "contract block is missing the game mode_key set");
  return { rows, modeSet };
}

const CONTRACT = parseContract(fs.readFileSync(DOC_PATH, "utf8"));

// --- fixtures (the GIVEN half; the doc owns the EXPECTED half) -----------------

// One /api/state shape per doc phase. The liveclient variants matter more than
// mode_key: RC pre-flips mode_key to the game mode during lobby + champ-select,
// so rows 2/3 deliberately carry a GAME mode with no live game to prove the gate
// is liveclient-driven. Row 4 is generated per doc-listed mode instead.
const PHASE_FIXTURES = Object.freeze({
  "League not running": [{ mode_key: "none" }],
  "client idle / lobby": [{ mode_key: "aram", liveclient: {} }],
  "champ-select": [{ mode_key: "sr" }],
  "post-game": [{ mode_key: "sr", liveclient: null }],
});

const IN_MATCH_PHASE = "in match";

function inMatchFixtures() {
  return CONTRACT.modeSet.map((m) => ({
    mode_key: m,
    liveclient: { activePlayer: { level: 11 }, gameData: { gameTime: 421.5 } },
  }));
}

// The exact pipeline main.js runs per poll (main.js:1073-1075 -> :982-:989).
function actionsForState(state) {
  const surface = ov.resolveSurface(
    state && state.mode_key,
    false,
    ov.liveGameFromState(state)
  );
  return ov.windowActionsWithPolicy(surface, {
    // Read the shipped default rather than a literal, so flipping keepCompanion
    // in src is a doc-contract failure instead of a silently weakened test.
    keepCompanion: ov.OVERLAY_SETTINGS_DEFAULTS.keepCompanion,
  });
}

// --- the contract -------------------------------------------------------------

test("contract parse is non-vacuous: 5 doc rows, each with a fixture", () => {
  assert.strictEqual(CONTRACT.rows.length, 5, "section 5 must carry exactly 5 phase rows");
  const docPhases = CONTRACT.rows.map((r) => r.phase).sort();
  const known = Object.keys(PHASE_FIXTURES).concat([IN_MATCH_PHASE]).sort();
  // Set-equality both ways: a renamed / added / removed doc row fails here rather
  // than quietly losing its assertions.
  assert.deepStrictEqual(docPhases, known);
});

for (const row of CONTRACT.rows) {
  test(`doc row ${JSON.stringify(row.phase)}: companion ${row.companion} / overlay ${row.overlay}`, () => {
    const fixtures =
      row.phase === IN_MATCH_PHASE ? inMatchFixtures() : PHASE_FIXTURES[row.phase];
    assert.ok(fixtures && fixtures.length > 0, `no fixture for doc phase ${row.phase}`);
    for (const state of fixtures) {
      const actions = actionsForState(state);
      const where = `${row.phase} / ${JSON.stringify(state.mode_key)}`;
      assert.strictEqual(actions.companion, row.companion, `companion @ ${where}`);
      assert.strictEqual(actions.overlay, row.overlay, `overlay @ ${where}`);
    }
  });
}

test("doc interaction cells match the shipped overlay interaction default", () => {
  const passiveRows = CONTRACT.rows.filter((r) => r.interaction === "passive");
  const activeRows = CONTRACT.rows.filter((r) => r.interaction === "active");
  assert.ok(passiveRows.length > 0, "no doc row claims a passive overlay");
  assert.strictEqual(activeRows.length, 0, "doc claims an ACTIVE default the shell does not ship");
  // "passive" in the table is exactly OVERLAY_DEFAULTS.clickThrough being true:
  // an ACTIVE-by-default overlay would eat the operator's clicks in-game.
  assert.strictEqual(ov.OVERLAY_DEFAULTS.clickThrough, true);
  for (const row of passiveRows) {
    assert.strictEqual(row.overlay, "show", `${row.phase} claims passive without showing`);
  }
});

test("every doc-listed game mode_key is a GAME_MODES member", () => {
  // Subset, not equality: the doc lists the five product modes and GAME_MODES
  // also carries a generic "game" alias (documented in the section-5 notes).
  for (const m of CONTRACT.modeSet) {
    assert.ok(ov.GAME_MODES.has(m), `doc lists mode ${m} but GAME_MODES does not`);
    assert.strictEqual(ov.surfaceForMode(m, true), ov.SURFACES.OVERLAY, m);
  }
});

test("doc note holds: liveclient gates the overlay, mode_key alone does not", () => {
  // The note under the table claims rows 2/3/5 land on the companion BECAUSE of
  // liveGameFromState, not phase handling. Prove the gate is load-bearing: the
  // same game mode_key flips surface on the liveclient alone.
  for (const m of CONTRACT.modeSet) {
    assert.strictEqual(
      actionsForState({ mode_key: m, liveclient: {} }).overlay,
      "hide",
      `empty liveclient must not show the HUD (${m})`
    );
    assert.strictEqual(
      actionsForState({ mode_key: m, liveclient: { gameData: { gameTime: 1 } } }).overlay,
      "show",
      `populated liveclient must show the HUD (${m})`
    );
  }
});

test("doc note holds: no fade state - windowActions only ever says show or hide", () => {
  const verbs = new Set();
  for (const surface of [ov.SURFACES.COMPANION, ov.SURFACES.OVERLAY, ov.SURFACES.HIDDEN]) {
    const a = ov.windowActions(surface);
    verbs.add(a.companion);
    verbs.add(a.overlay);
  }
  assert.deepStrictEqual([...verbs].sort(), ["hide", "show"]);
});

test("doc note holds: the hotkey force-hide beats every row, keepCompanion included", () => {
  for (const m of CONTRACT.modeSet.concat(["none", "client"])) {
    const surface = ov.resolveSurface(m, true, true);
    assert.strictEqual(surface, ov.SURFACES.HIDDEN, m);
    assert.deepStrictEqual(ov.windowActionsWithPolicy(surface, { keepCompanion: true }), {
      companion: "hide",
      overlay: "hide",
    });
  }
});
