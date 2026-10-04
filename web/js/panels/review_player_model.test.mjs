// web/js/panels/review_player_model.test.mjs
//
// RM-641 (directive X-41, ADR-016). Pure-logic tests for the S5 Replay
// video lane interaction model. Behaviour observed in external reference E,
// re-implemented clean-room; every constant here is our own. Run with
// `node --test`; gated from pytest by tests/test_web_panels_node_suite.py.

import test from "node:test";
import assert from "node:assert";

import {
  CLUSTER_RADIUS_PX, OPEN_LEAD_S, ICON_PRIORITY,
  markerX, clusterMarkers, pickIcon, markersFromSidecar, openTimeS,
  videoTimeFor, isTypingTarget, hotkeyAction, seekTarget, costMoments,
} from "./review_player_model.js";

// ---- clustering ------------------------------------------------------------

test("constants are our own and sane", () => {
  assert.strictEqual(OPEN_LEAD_S, 2);
  assert.ok(CLUSTER_RADIUS_PX > 0 && CLUSTER_RADIUS_PX < 40);
});

test("markerX maps time onto the lane and clamps", () => {
  assert.strictEqual(markerX(50, 100, 200), 100);
  assert.strictEqual(markerX(-5, 100, 200), 0);
  assert.strictEqual(markerX(500, 100, 200), 200);
  assert.strictEqual(markerX(5, 0, 200), 0);
});

test("dense run cannot chain: radius is measured from the cluster ORIGIN", () => {
  // 1 px per second; radius 10. Markers every 6 px: a chaining algorithm
  // (distance to the previous member) would swallow all five.
  const ms = [0, 6, 12, 18, 24].map((t) => ({ t, name: "ChampionKill" }));
  const cl = clusterMarkers(ms, 1000, 1000, 10);
  assert.deepStrictEqual(cl.map((c) => c.members.length), [2, 2, 1]);
  assert.deepStrictEqual(cl.map((c) => c.x), [0, 12, 24]);
  assert.deepStrictEqual(cl.map((c) => c.t), [0, 12, 24]);
});

test("a marker exactly at the radius joins; one past starts a new cluster", () => {
  const cl = clusterMarkers([{ t: 0 }, { t: 10 }, { t: 10.5 }], 1000, 1000, 10);
  assert.deepStrictEqual(cl.map((c) => c.members.length), [2, 1]);
});

test("clusterMarkers sorts its input and ignores non-finite times", () => {
  const cl = clusterMarkers([{ t: 50 }, { t: NaN }, { t: 0 }, { t: null }], 100, 100, 5);
  assert.deepStrictEqual(cl.map((c) => c.t), [0, 50]);
});

test("clustering uses our default radius when none is given", () => {
  const near = clusterMarkers([{ t: 0 }, { t: CLUSTER_RADIUS_PX }], 1000, 1000);
  assert.strictEqual(near.length, 1);
  const far = clusterMarkers([{ t: 0 }, { t: CLUSTER_RADIUS_PX + 1 }], 1000, 1000);
  assert.strictEqual(far.length, 2);
});

// ---- icon priority -----------------------------------------------------------

test("priority table: own death outranks every other kind", () => {
  const icon = pickIcon([
    { name: "BaronKill" }, { name: "ChampionKill", own_death: true },
    { name: "TurretKilled" },
  ]);
  assert.strictEqual(icon, "death");
});

test("priority table: objective outranks a takedown, takedown outranks a turret", () => {
  assert.strictEqual(pickIcon([{ name: "TurretKilled" }, { name: "DragonKill" },
                               { name: "ChampionKill" }]), "objective");
  assert.strictEqual(pickIcon([{ name: "TurretKilled" }, { name: "ChampionKill" }]),
                     "kill");
  assert.strictEqual(pickIcon([{ name: "InhibKilled" }]), "structure");
  assert.strictEqual(pickIcon([{ name: "SomethingNew" }]), "event");
  assert.strictEqual(pickIcon([]), "event");
});

test("priority table is ordered and unique", () => {
  const ranks = ICON_PRIORITY.map((r) => r.icon);
  assert.strictEqual(new Set(ranks).size, ranks.length);
  assert.strictEqual(ranks[0], "death");
  assert.strictEqual(ranks[ranks.length - 1], "event");
});

test("clusters carry the winning icon", () => {
  const cl = clusterMarkers([{ t: 0, name: "TurretKilled" },
                             { t: 1, name: "ChampionKill", own_death: true }],
                            100, 100, 5);
  assert.strictEqual(cl[0].icon, "death");
});

// ---- sidecar consumption ------------------------------------------------------------

const SIDECAR = {
  schema: 1, status: "final", match_id: "123", owner: "rc",
  obs_output_path: "/synthetic/rec/a.mp4", game_time_offset_s: 31.5,
  bookmarks: [
    { event_id: 3, name: "ChampionKill", game_time: 300, video_time: 331.5,
      provisional: false, own_death: true },
    { event_id: 1, name: "DragonKill", game_time: 100, video_time: 131.5,
      provisional: false },
    { event_id: 2, name: "TurretKilled", game_time: 200, video_time: null,
      provisional: true },
  ],
};

test("markersFromSidecar reads video_time, falls back to game_time + offset", () => {
  const ms = markersFromSidecar(SIDECAR);
  assert.deepStrictEqual(ms.map((m) => m.t), [131.5, 231.5, 331.5]);
  assert.deepStrictEqual(ms.map((m) => !!m.own_death), [false, false, true]);
});

test("markersFromSidecar tolerates junk", () => {
  assert.deepStrictEqual(markersFromSidecar(null), []);
  assert.deepStrictEqual(markersFromSidecar({ bookmarks: "x" }), []);
  assert.deepStrictEqual(markersFromSidecar({ bookmarks: [null, 7, { name: "A" }] }), []);
});

test("open at aligned game start minus 2 s, never before the file start", () => {
  assert.strictEqual(openTimeS(SIDECAR), 29.5);
  assert.strictEqual(openTimeS({ game_time_offset_s: 1 }), 0);
  assert.strictEqual(openTimeS({ game_time_offset_s: null }), 0);
  assert.strictEqual(openTimeS({}), 0);
  assert.strictEqual(openTimeS(null), 0);
});

test("videoTimeFor clamps to the file start", () => {
  assert.strictEqual(videoTimeFor(10, 5), 15);
  assert.strictEqual(videoTimeFor(1, -30), 0);
  assert.strictEqual(videoTimeFor(10, undefined), 10);
});

// ---- typing-aware hotkeys --------------------------------------------------------------

const BODY = { tag: "BODY" };
const FIELD = { tag: "INPUT", type: "text" };
const MARKER = { tag: "BUTTON", marker: true };
const k = (key, target = BODY, mods = {}) => ({ key, target, ...mods });

test("isTypingTarget: text fields and contenteditable are typing; toggles are not", () => {
  assert.strictEqual(isTypingTarget(FIELD), true);
  assert.strictEqual(isTypingTarget({ tag: "INPUT" }), true);
  assert.strictEqual(isTypingTarget({ tag: "TEXTAREA" }), true);
  assert.strictEqual(isTypingTarget({ tag: "DIV", editable: true }), true);
  assert.strictEqual(isTypingTarget({ tag: "INPUT", type: "checkbox" }), false);
  assert.strictEqual(isTypingTarget({ tag: "INPUT", type: "range" }), false);
  assert.strictEqual(isTypingTarget(MARKER), false);
  assert.strictEqual(isTypingTarget(null), false);
});

test("bracket and d/D keys map to marker and death navigation", () => {
  assert.deepStrictEqual(hotkeyAction(k("]")), { type: "next-marker" });
  assert.deepStrictEqual(hotkeyAction(k("[")), { type: "prev-marker" });
  assert.deepStrictEqual(hotkeyAction(k("d")), { type: "next-death" });
  assert.deepStrictEqual(hotkeyAction(k("D", BODY, { shiftKey: true })),
                         { type: "prev-death" });
  assert.strictEqual(hotkeyAction(k("x")), null);
});

test("plain keys stand down while typing", () => {
  for (const key of ["]", "[", "d", "D", " "]) {
    assert.strictEqual(hotkeyAction(k(key, FIELD)), null, `key ${JSON.stringify(key)}`);
  }
});

test("modifier+Space plays from inside a field", () => {
  assert.deepStrictEqual(hotkeyAction(k(" ", FIELD, { ctrlKey: true })),
                         { type: "toggle-play" });
  assert.deepStrictEqual(hotkeyAction(k(" ", FIELD, { altKey: true })),
                         { type: "toggle-play" });
  // Shift+Space types a space in a field; it is not our modifier.
  assert.strictEqual(hotkeyAction(k(" ", FIELD, { shiftKey: true })), null);
});

test("browser shortcuts are never hijacked", () => {
  assert.strictEqual(hotkeyAction(k("d", BODY, { ctrlKey: true })), null);
  assert.strictEqual(hotkeyAction(k("]", BODY, { metaKey: true })), null);
});

test("Escape hands focus back, from a field or from a marker", () => {
  assert.deepStrictEqual(hotkeyAction(k("Escape", FIELD)), { type: "release-focus" });
  assert.deepStrictEqual(hotkeyAction(k("Escape", MARKER)), { type: "release-focus" });
});

test("Space on a focused marker toggles play and does NOT re-seek", () => {
  const a = hotkeyAction(k(" ", MARKER));
  assert.deepStrictEqual(a, { type: "toggle-play" });
  assert.strictEqual(seekTarget(a, { markers: [5, 10], deaths: [], current: 0 }), null);
});

test("seekTarget walks markers and deaths strictly past the playhead", () => {
  const st = { markers: [10, 20, 30], deaths: [15, 25], current: 20 };
  assert.strictEqual(seekTarget({ type: "next-marker" }, st), 30);
  assert.strictEqual(seekTarget({ type: "prev-marker" }, st), 10);
  assert.strictEqual(seekTarget({ type: "next-death" }, st), 25);
  assert.strictEqual(seekTarget({ type: "prev-death" }, st), 15);
  assert.strictEqual(seekTarget({ type: "next-marker" }, { ...st, current: 30 }), null);
  assert.strictEqual(seekTarget({ type: "prev-death" }, { ...st, current: 15 }), null);
  assert.strictEqual(seekTarget(null, st), null);
});

test("prev-marker just after a seek skips the marker we are sitting on", () => {
  // Seeking lands a hair past the marker; [ must go to the one before it.
  const st = { markers: [10, 20], deaths: [], current: 20.1 };
  assert.strictEqual(seekTarget({ type: "prev-marker" }, st), 10);
});

// ---- PGR cost moments -----------------------------------------------------------------

const WPA_EVENTS = [
  { game_time: 100, type: "CHAMPION_KILL", wpa: -0.05 },
  { game_time: 200, type: "ELITE_MONSTER_KILL", wpa: 0.09 },
  { game_time: 300, type: "BUILDING_KILL", wpa: -0.002 },
  { game_time: 400, type: "CHAMPION_KILL", wpa: -0.12 },
];

test("costMoments: team 100 costs are negative wpa, sorted by time", () => {
  const cm = costMoments(WPA_EVENTS, 100);
  assert.deepStrictEqual(cm.map((c) => c.game_time), [100, 400]);
  assert.ok(Math.abs(cm[1].cost - 0.12) < 1e-9);
});

test("costMoments: team 200 flips the sign", () => {
  assert.deepStrictEqual(costMoments(WPA_EVENTS, 200).map((c) => c.game_time), [200]);
});

test("costMoments: limit keeps the biggest costs, unknown team yields nothing", () => {
  assert.deepStrictEqual(costMoments(WPA_EVENTS, 100, { limit: 1 }).map((c) => c.game_time),
                         [400]);
  assert.deepStrictEqual(costMoments(WPA_EVENTS, null), []);
  assert.deepStrictEqual(costMoments(null, 100), []);
});
