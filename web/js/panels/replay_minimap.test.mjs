// web/js/panels/replay_minimap.test.mjs
//
// RM-612 (directive X-12, external reference I) - pure-logic tests for the
// past-match minimap layer on the replay scrubber. Run with `node --test`
// (tests/test_replay_minimap_crosscheck.py executes this file from pytest).
//
// The fixture below is SYNTHETIC: champion names only, no player names, no
// real match id. Coordinates are invented round numbers.
//
// What is pinned:
//   - deathTimerS is a faithful port of core.post_game_score.calculate_death_timer
//     (shared table in tests/fixtures/replay_minimap_death_timer.json).
//   - a victim is NEVER drawn inside its death window.
//   - no sample taken before a death is ever used after that death (no halo
//     straddles a death); the respawn places the champion at its fountain.
//   - a frame inside a death window that echoes the kill position is dropped.
//   - revives (a frame or a second death that contradicts the window) are
//     flagged and the victim is drawn as alive.
//   - queue 2400 has no map.

import test from "node:test";
import assert from "node:assert";
import { readFileSync } from "node:fs";

import {
  deathTimerS, haloUnits, monogram, mapKindForQueue, buildModel, stateAt,
  worldToCanvas, HALO_MAX_UNITS, HALO_MEAN_UNITS, FOUNTAIN_FALLBACK,
} from "./replay_minimap.js";

const DT_TABLE = JSON.parse(readFileSync(
  new URL("../../../tests/fixtures/replay_minimap_death_timer.json", import.meta.url),
  "utf-8"));

// --- synthetic match ---------------------------------------------------------
// pid 1, 2 = team 100 (tracked = pid 1); pid 6, 7 = team 200.
const F100 = [400, 400], F200 = [14300, 14400];
function frame(t, rows) {
  return {
    timestamp_ms: t, minute: Math.round(t / 6000) / 10,
    entries: rows.map(([pid, level, pos]) => ({ participant_id: pid, level, pos })),
  };
}
function syntheticMatch() {
  return {
    match_id: "TEST_1", queue_id: 420,
    tracked: { champion_id: 1 },
    participants: [
      { participant_id: 1, team_id: 100, champion_id: 1, champion_name: "Annie" },
      { participant_id: 2, team_id: 100, champion_id: 86, champion_name: "Garen" },
      { participant_id: 6, team_id: 200, champion_id: 145, champion_name: "Kai'Sa" },
      { participant_id: 7, team_id: 200, champion_id: 64, champion_name: "Lee Sin" },
    ],
    snapshots: [
      frame(0,      [[1, 1, F100], [2, 1, F100], [6, 1, F200], [7, 1, F200]]),
      frame(60000,  [[1, 3, [4000, 4000]], [2, 3, [2000, 9000]], [6, 3, [5200, 5200]], [7, 11, [9500, 9500]]]),
      frame(120000, [[1, 5, [6000, 6000]], [2, 11, [3000, 8000]], [6, 6, [8000, 8000]],
                     // pid 7 died at 100000 (level 11 -> 35 s window). A frame at
                     // 120000 that is far from both the kill spot and the fountain
                     // contradicts the window -> revive.
                     [7, 11, [3000, 9000]]]),
      frame(180000, [[1, 7, [6500, 6500]],
                     // pid 2 died at 170000 at [7000, 7000]: this frame echoes the
                     // kill position (Riot keeps a dead champion's frame at its
                     // death spot) and must be dropped.
                     [2, 11, [7000, 7000]],
                     [6, 11, [8100, 8100]], [7, 11, [3500, 9100]]]),
      frame(240000, [[1, 8, [7000, 6000]], [2, 11, [1500, 1500]], [6, 11, [8200, 8200]], [7, 11, [4000, 9000]]]),
    ],
    kills: [
      // pid 6 kills pid 1 at 70 s; pid 1 level 3 at the 60 s frame -> 12 s window.
      { timestamp_ms: 70000, killer_id: 6, victim_id: 1, assists: [], pos: [5000, 5000] },
      // pid 2 kills pid 7 at 100 s; pid 7 is level 11 at the 60 s frame -> 35 s window.
      { timestamp_ms: 100000, killer_id: 2, victim_id: 7, assists: [], pos: [9000, 9000] },
      // pid 6 kills pid 2 at 170 s; pid 2 is level 11 at the 120 s frame -> 35 s
      // window, so the 180 s frame falls inside it.
      { timestamp_ms: 170000, killer_id: 6, victim_id: 2, assists: [], pos: [7000, 7000] },
      // pid 1 kills pid 6 at 200 s, then pid 2 kills pid 6 AGAIN at 210 s,
      // inside the first window -> the first death was revived (GA / Zilean).
      { timestamp_ms: 200000, killer_id: 1, victim_id: 6, assists: [], pos: [8200, 8000] },
      { timestamp_ms: 210000, killer_id: 2, victim_id: 6, assists: [], pos: [8300, 8100] },
    ],
  };
}

function windowsOf(model, pid) { return model.windows.get(pid) || []; }

// --- death timer port ----------------------------------------------------------
test("deathTimerS matches core.post_game_score.calculate_death_timer on the shared table", () => {
  assert.ok(DT_TABLE.cases.length >= 15, "cross-check table is not vacuous");
  for (const c of DT_TABLE.cases) {
    const got = deathTimerS(c.level, c.time_ms);
    assert.ok(Math.abs(got - c.seconds) < 1e-9,
      `level ${c.level} t ${c.time_ms}: js ${got} != py ${c.seconds}`);
  }
});

// --- death windows -------------------------------------------------------------
test("death window = [kill_t, kill_t + deathTimerS(level at last frame <= kill_t))", () => {
  const m = buildModel(syntheticMatch());
  const w = windowsOf(m, 1);
  assert.strictEqual(w.length, 1);
  assert.strictEqual(w[0].start, 70000);
  assert.strictEqual(w[0].end, 70000 + deathTimerS(3, 70000) * 1000);
  assert.strictEqual(w[0].revived, false);
});

test("the victim is NOT drawn anywhere inside its death window", () => {
  const m = buildModel(syntheticMatch());
  let checked = 0;
  for (const pid of [1, 2]) {
    for (const w of windowsOf(m, pid)) {
      assert.strictEqual(w.revived, false);
      for (let t = w.start; t < w.end; t += 250) {
        const s = stateAt(m, pid, t);
        assert.strictEqual(s.visible, false, `pid ${pid} drawn at ${t} inside [${w.start}, ${w.end})`);
        assert.strictEqual(s.dead, true);
        checked++;
      }
    }
  }
  assert.ok(checked > 100, "sweep is not vacuous");
});

test("at respawn the victim is placed at its own fountain with zero sample age", () => {
  const m = buildModel(syntheticMatch());
  const w = windowsOf(m, 1)[0];
  const s = stateAt(m, 1, w.end);
  assert.strictEqual(s.visible, true);
  assert.strictEqual(s.src, "respawn");
  assert.deepStrictEqual(s.pos, m.fountains[100]);
  assert.strictEqual(s.ageS, 0);
  assert.strictEqual(s.haloUnits, 0);
});

test("no sample from before a death is ever used after it (no halo straddles a death)", () => {
  const match = syntheticMatch();
  const m = buildModel(match);
  let checked = 0;
  for (const p of match.participants) {
    const pid = p.participant_id;
    for (let t = 0; t <= 240000; t += 500) {
      const s = stateAt(m, pid, t);
      if (!s.visible) continue;
      for (const w of windowsOf(m, pid)) {
        if (w.revived || t < w.start) continue;
        assert.ok(s.sampleT >= w.end,
          `pid ${pid} at ${t} uses sample ${s.sampleT} from before death [${w.start}, ${w.end})`);
        checked++;
      }
    }
  }
  assert.ok(checked > 50, "straddle sweep is not vacuous");
});

test("stateAt never reaches back across a death even with no respawn sample", () => {
  // Hand-built model: the only sample predates the death. buildModel always
  // adds a respawn sample (which hides this on its own), so this pins the
  // floor inside stateAt independently - mutation-found 2026-10-04.
  const model = {
    windows: new Map([[1, [{ start: 70000, end: 82000, killPos: [5000, 5000], revived: false }]]]),
    samples: new Map([[1, [{ t: 60000, pos: [4000, 4000], src: "frame" }]]]),
  };
  assert.strictEqual(stateAt(model, 1, 65000).visible, true);
  assert.strictEqual(stateAt(model, 1, 75000).visible, false);
  const after = stateAt(model, 1, 90000);
  assert.strictEqual(after.visible, false, "a pre-death sample was used after the death");
});

test("a frame inside a death window that echoes the kill spot is dropped", () => {
  const m = buildModel(syntheticMatch());
  const w = windowsOf(m, 2)[0];
  assert.ok(w.start < 180000 && 180000 < w.end, "fixture: the 180 s frame is inside the window");
  assert.ok(!(m.samples.get(2) || []).some((x) => x.t === 180000),
    "the death-spot echo frame must not become a sample");
  // 206 s: after the respawn at 205 s, before pid 2's own kill at 210 s.
  const s = stateAt(m, 2, 206000);
  assert.strictEqual(s.src, "respawn");
  assert.strictEqual(s.sampleT, w.end);
  assert.notDeepStrictEqual(s.pos, [7000, 7000]);
});

test("revive: a frame contradicting the window flags it and the victim stays drawn", () => {
  const m = buildModel(syntheticMatch());
  const w = windowsOf(m, 7)[0];
  assert.strictEqual(w.revived, true);
  const s = stateAt(m, 7, 110000);
  assert.strictEqual(s.visible, true);
  assert.strictEqual(s.revive, true);
  assert.ok(m.flags.some((f) => f.pid === 7 && f.kind === "revive"));
});

test("revive: dying again inside the window flags the first death", () => {
  const m = buildModel(syntheticMatch());
  const ws = windowsOf(m, 6);
  assert.strictEqual(ws.length, 2);
  assert.strictEqual(ws[0].revived, true);
  assert.strictEqual(ws[1].revived, false);
  assert.strictEqual(stateAt(m, 6, 211000).visible, false);
});

test("a fountain frame inside the window is early-respawn evidence, not a revive", () => {
  const match = syntheticMatch();
  // pid 1 level 18 at the 60 s frame -> 52.5 s window from 70 s; the 120 s
  // frame is at the fountain.
  match.snapshots[1].entries[0].level = 18;
  match.snapshots[2].entries[0].pos = [420, 380];
  const m = buildModel(match);
  const w = windowsOf(m, 1)[0];
  assert.strictEqual(w.revived, false);
  assert.strictEqual(w.end, 120000);
  assert.strictEqual(stateAt(m, 1, 119999).visible, false);
  assert.strictEqual(stateAt(m, 1, 120000).src, "respawn");
});

// --- snapping at kill events -----------------------------------------------------
test("the killer snaps to the exact kill position at the kill time", () => {
  const m = buildModel(syntheticMatch());
  const s = stateAt(m, 6, 70000);
  assert.strictEqual(s.src, "kill");
  assert.deepStrictEqual(s.pos, [5000, 5000]);
  assert.strictEqual(s.ageS, 0);
});

test("a killer who is dead at the kill time (posthumous kill) gets no kill sample", () => {
  const match = syntheticMatch();
  // pid 2 is dead from 170 s; credit it a posthumous kill at 175 s.
  match.kills.push({ timestamp_ms: 175000, killer_id: 2, victim_id: 7, assists: [], pos: [100, 14000] });
  const m = buildModel(match);
  assert.ok(!(m.samples.get(2) || []).some((x) => x.src === "kill" && x.t === 175000));
});

// --- halo ------------------------------------------------------------------------
test("halo grows with sample age, hits the measured mean at 30 s, and is capped", () => {
  assert.strictEqual(haloUnits(0), 0);
  assert.ok(Math.abs(haloUnits(30) - HALO_MEAN_UNITS) < 1e-9);
  let prev = -1;
  for (let a = 0; a <= 600; a += 5) {
    const h = haloUnits(a);
    assert.ok(h >= prev, "monotonic");
    assert.ok(h <= HALO_MAX_UNITS, "capped");
    prev = h;
  }
  assert.strictEqual(haloUnits(600), HALO_MAX_UNITS);
  assert.strictEqual(haloUnits(-5), 0);
});

test("between frames the halo reflects the age of the last-known sample (no interpolation)", () => {
  const m = buildModel(syntheticMatch());
  const s = stateAt(m, 1, 150000);
  assert.strictEqual(s.src, "frame");
  assert.deepStrictEqual(s.pos, [6000, 6000]);     // last-known, not a blend toward 6500
  assert.strictEqual(s.ageS, 30);
  assert.ok(s.haloUnits > 0);
});

// --- modes / helpers -----------------------------------------------------------------
test("queue 2400 (no timeline) has no map; SR and ARAM queues do", () => {
  assert.strictEqual(mapKindForQueue(2400), null);
  assert.strictEqual(mapKindForQueue(420), "sr");
  assert.strictEqual(mapKindForQueue(450), "aram");
  const match = syntheticMatch();
  match.queue_id = 2400;
  assert.strictEqual(buildModel(match).hidden, true);
});

test("fountains come from the match's own frame 0, else the measured fallback", () => {
  const m = buildModel(syntheticMatch());
  assert.deepStrictEqual(m.fountains[100], F100);
  assert.deepStrictEqual(m.fountains[200], F200);
  const match = syntheticMatch();
  match.snapshots.shift();
  const m2 = buildModel(match);
  assert.deepStrictEqual(m2.fountains[100], FOUNTAIN_FALLBACK.sr[100]);
});

test("monogram is two ASCII letters", () => {
  assert.strictEqual(monogram("Lee Sin"), "LS");
  assert.strictEqual(monogram("Kai'Sa"), "KA");
  assert.strictEqual(monogram("Annie"), "AN");
  assert.strictEqual(monogram(""), "??");
  assert.strictEqual(monogram(null), "??");
});

test("worldToCanvas flips y (game origin bottom-left)", () => {
  const [x, y] = worldToCanvas([0, 0], "sr", 100, 100);
  assert.strictEqual(x, 0);
  assert.strictEqual(y, 100);
  const [x2, y2] = worldToCanvas([14800, 14800], "sr", 100, 100);
  assert.strictEqual(x2, 100);
  assert.strictEqual(y2, 0);
});
