// rc-shell/test/overlay_phase_contract.test.js
//
// RC-PHASE-SURFACES contract: docs/OVERLAY_DOCTRINE.md section 10 ships a
// phase -> (window, companion view, field widgets) table. This test PARSES THE
// TABLE OFF DISK and derives every expectation from the parsed cells, the same
// shape as overlay_state_contract.test.js over docs/ELECTRON_OVERLAY.md section
// 5, so editing the doc alone turns this suite red (memory
// feedback_contract_test_must_read_the_contract_from_disk).
//
// The test supplies only the GIVEN side as literals: one /api/state-shaped
// fixture per doc phase. The window column is driven through the exact pipeline
// main.js runs per poll; the phase + field columns through web/js/lib/
// overlay_phase.js. The companion view column is pinned in pytest against
// dashboard/view_router_state.py (tests/snapshot_panels/
// test_overlay_phase_surfaces.py).

"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const url = require("node:url");

const ov = require("../src/overlay_state");

const ROOT = path.join(__dirname, "..", "..");
const DOC_PATH = path.join(ROOT, "docs", "OVERLAY_DOCTRINE.md");

function parseContract(text) {
  const secStart = text.indexOf("## 10. PHASE SURFACES");
  assert.notStrictEqual(secStart, -1, "section 10 heading missing from the doctrine");
  const secEnd = text.indexOf("\n## ", secStart + 1);
  const section = text.slice(secStart, secEnd === -1 ? undefined : secEnd);
  const fenceOpen = section.indexOf("```");
  assert.notStrictEqual(fenceOpen, -1, "section 10 has no fenced contract block");
  const bodyStart = section.indexOf("\n", fenceOpen) + 1;
  const fenceClose = section.indexOf("```", bodyStart);
  assert.notStrictEqual(fenceClose, -1, "section 10 contract block is unterminated");
  const lines = section.slice(bodyStart, fenceClose).split("\n");
  assert.match(lines[0], /^phase\s+window\s+companion\s+field\s*$/);
  assert.match(lines[1], /^-+\s+-+\s+-+\s+-+\s*$/);
  const rows = [];
  for (const raw of lines.slice(2)) {
    const line = raw.trimEnd();
    if (line.trim() === "") {
      continue;
    }
    const cells = line.split(/\s{2,}/).map((c) => c.trim());
    assert.strictEqual(cells.length, 4, `contract row is not 4 columns: ${JSON.stringify(line)}`);
    const [phase, window_, companion, field] = cells;
    assert.ok(["show", "hide"].includes(window_), `unmodelled window token ${window_}`);
    rows.push({ phase, window: window_, companion, field: field.split(" ") });
  }
  return rows;
}

const ROWS = parseContract(fs.readFileSync(DOC_PATH, "utf8"));

// The GIVEN half. RC pre-flips mode_key to the game mode in the lobby and champ
// select, so those rows carry a game mode on purpose.
const FEED = { level: 6, game_time_s: 120 };
const FIXTURES = Object.freeze({
  lobby: [
    { mode_key: "aram", lcu: { phase: "Lobby" }, liveclient: {} },
    { mode_key: "client", lcu: { phase: "None" }, liveclient: {} },
  ],
  "champ-select": [
    { mode_key: "sr", lcu: { phase: "ChampSelect" }, liveclient: {} },
    { mode_key: "aram", lcu: { phase: "ChampSelect" } },
  ],
  loading: [
    { mode_key: "sr", lcu: { phase: "GameStart" }, liveclient: {} },
    { mode_key: "sr", lcu: { phase: "InProgress" }, liveclient: {} },
    { mode_key: "tft", lcu: { phase: "GameStart" }, liveclient: {} },
  ],
  "in-game": [
    { mode_key: "sr", lcu: { phase: "InProgress" }, liveclient: FEED },
    { mode_key: "aram", lcu: {}, liveclient: FEED },
    { mode_key: "tft", lcu: { phase: "InProgress" }, liveclient: {} },
  ],
  "post-game": [
    { mode_key: "sr", lcu: { phase: "EndOfGame" }, liveclient: {} },
    { mode_key: "sr", lcu: { phase: "WaitingForStats" }, liveclient: null },
  ],
});

function windowVerb(state) {
  const surface = ov.resolveSurface(state.mode_key, false, ov.liveGameFromState(state));
  return ov.windowActionsWithPolicy(surface, {
    keepCompanion: ov.OVERLAY_SETTINGS_DEFAULTS.keepCompanion,
  }).overlay;
}

async function phaseModule() {
  const file = path.join(ROOT, "web", "js", "lib", "overlay_phase.js");
  return import(url.pathToFileURL(file).href);
}

test("contract parse is non-vacuous: one doc row per phase, each with a fixture", async () => {
  const { OVERLAY_PHASES } = await phaseModule();
  const docPhases = ROWS.map((r) => r.phase).sort();
  assert.deepStrictEqual(docPhases, OVERLAY_PHASES.slice().sort());
  assert.deepStrictEqual(docPhases, Object.keys(FIXTURES).sort());
});

for (const row of ROWS) {
  test(`doc row ${row.phase}: window ${row.window}`, async () => {
    const { overlayPhaseFromState } = await phaseModule();
    for (const state of FIXTURES[row.phase]) {
      const where = JSON.stringify(state);
      assert.strictEqual(overlayPhaseFromState(state), row.phase, `phase @ ${where}`);
      assert.strictEqual(windowVerb(state), row.window, `window @ ${where}`);
    }
  });

  test(`doc row ${row.phase}: field column equals the code map`, async () => {
    const { PHASE_WIDGETS } = await phaseModule();
    if (row.field.length === 1 && row.field[0] === "all") {
      assert.strictEqual(row.phase, "in-game", "only the in-game row may claim the whole field");
      assert.strictEqual(PHASE_WIDGETS[row.phase], undefined, "in-game has no list: every widget");
      return;
    }
    assert.ok(row.field.includes("w-launcher"), `${row.phase} must keep the escape hatch`);
    assert.deepStrictEqual(
      row.field.filter((id) => id !== "w-launcher").sort(),
      PHASE_WIDGETS[row.phase].slice().sort()
    );
  });
}

test("the post-game row's stale-feed note holds: window up, field stripped", async () => {
  // The doc's reason the field gate does observable work today: :2999 can still
  // answer after the LCU says the game ended, so the shell keeps the window up.
  const { overlayPhaseFromState, widgetAllowedInPhase } = await phaseModule();
  const state = { mode_key: "sr", lcu: { phase: "EndOfGame" }, liveclient: FEED };
  assert.strictEqual(windowVerb(state), "show");
  assert.strictEqual(overlayPhaseFromState(state), "post-game");
  assert.strictEqual(widgetAllowedInPhase("w-call", "post-game"), false);
});

test("every id the doc names exists in the registry or is the launcher", async () => {
  const layout = fs.readFileSync(path.join(ROOT, "web", "js", "lib", "overlay_layout.js"), "utf8");
  for (const row of ROWS) {
    for (const id of row.field) {
      if (id === "all") {
        continue;
      }
      assert.ok(layout.includes(`id: "${id}"`), `doc names ${id}, the registry does not`);
    }
  }
});
