// S144-U-215 (queue defect B#3): the BUILD pane at a finished build.
// _amBuildPainted decides what the retain-last-good guard may keep: only a
// paint _renderAmBuildBody stamped (data-am-build-sig), never the index.html
// scaffold line. _bmLiveEmptyText is the empty Daemon Slayer row's text.
// Browser half: tests/snapshot_panels/test_ui_mock_active_match_complete.py.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  _amBuildPainted, _amLiveclientOwnedIds, _bmLiveEmptyText, _shouldRetainBuild,
} from "./active_match.js";

const pane = (html, sig) => ({
  innerHTML: html,
  dataset: sig === undefined ? {} : { amBuildSig: sig },
});

test("the index.html scaffold is content but not a paint", () => {
  const scaffold = pane('<div class="am-empty">will render here mid-game.</div>');
  assert.equal(_amBuildPainted(scaffold), false);
  // So the guard lets a champion-only tick replace it.
  assert.equal(_shouldRetainBuild("Jinx", 0, 0, _amBuildPainted(scaffold)), false);
});

test("a stamped paint is kept over an empty tick", () => {
  const painted = pane('<div class="bm-module"></div>', '{"p":[3089]}');
  assert.equal(_amBuildPainted(painted), true);
  assert.equal(_shouldRetainBuild("", 0, 0, _amBuildPainted(painted)), true);
  // A radial re-render clears the sig to "" before repainting: still a paint.
  assert.equal(_amBuildPainted(pane("<div></div>", "")), true);
});

test("an emptied or absent pane is not a paint", () => {
  assert.equal(_amBuildPainted(pane("", '{"p":[]}')), false);
  assert.equal(_amBuildPainted(null), false);
  assert.equal(_amBuildPainted(undefined), false);
});

test("the live row speaks only at six items", () => {
  assert.equal(_bmLiveEmptyText(6), "All six item slots full");
  assert.equal(_bmLiveEmptyText(7), "All six item slots full");
  for (const n of [0, 1, 5, -1, NaN, null, undefined, "x"]) {
    assert.equal(_bmLiveEmptyText(n), "", String(n));
  }
});

// S144-U-216: the full-inventory line counts only what the liveclient block
// itself says the operator owns. The coach items_display name fallback can
// carry the trinket (5 items + trinket = 6), so it never feeds the count.
const me = (items) => ({
  activePlayer: { summonerName: "SamplePlayer", riotIdGameName: "SamplePlayer" },
  allPlayers: [
    { summonerName: "Other", riotIdGameName: "Other", items: [] },
    { summonerName: "SamplePlayer", riotIdGameName: "SamplePlayer", items },
  ],
});
const slots = (ids) => ids.map((itemID, slot) => ({ itemID, slot }));

test("the server owned_item_ids list wins when it is non-empty", () => {
  const lc = { ...me(slots([1001])), owned_item_ids: [3006, "6676", " 3031 ", "", null] };
  assert.deepEqual(_amLiveclientOwnedIds(lc), ["3006", "6676", "3031"]);
});

test("an empty server list falls back to the roster's own slots 0-5 only", () => {
  // Six slotted items plus the trinket in slot 6: six, never seven.
  const lc = { ...me(slots([3006, 6676, 3031, 3036, 3085, 3072, 3363])), owned_item_ids: [] };
  assert.deepEqual(_amLiveclientOwnedIds(lc),
    ["3006", "6676", "3031", "3036", "3085", "3072"]);
  assert.equal(_bmLiveEmptyText(_amLiveclientOwnedIds(lc).length), "All six item slots full");
  // Five items plus the trinket: five - no full-inventory line.
  const five = { ...me(slots([3006, 6676, 3031, 3036, 3085, 3363]).map(
    (it, i) => (i === 5 ? { ...it, slot: 6 } : it))), owned_item_ids: [] };
  assert.equal(_amLiveclientOwnedIds(five).length, 5);
  assert.equal(_bmLiveEmptyText(_amLiveclientOwnedIds(five).length), "");
});

test("an unmatched active player counts zero, whatever the coach names say", () => {
  // The server could not match the active player (owned_item_ids []) and the
  // lean roster has no row for them either: the count is 0, not the six
  // names the coach items_display fallback would resolve.
  const lc = {
    activePlayer: { summonerName: "Renamed#TAG", riotIdGameName: "Renamed" },
    allPlayers: [{ summonerName: "Other", riotIdGameName: "Other",
      items: slots([3006, 6676, 3031, 3036, 3085, 3072]) }],
    owned_item_ids: [],
  };
  assert.deepEqual(_amLiveclientOwnedIds(lc), []);
  assert.equal(_bmLiveEmptyText(_amLiveclientOwnedIds(lc).length), "");
});

test("no or malformed liveclient block counts zero", () => {
  for (const lc of [null, undefined, {}, "x", 7, { owned_item_ids: "3006" },
    { activePlayer: {}, allPlayers: "x" }]) {
    assert.deepEqual(_amLiveclientOwnedIds(lc), [], String(lc));
  }
});
