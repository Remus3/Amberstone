// S144-U-215 (queue defect B#3): the BUILD pane at a finished build.
// _amBuildPainted decides what the retain-last-good guard may keep: only a
// paint _renderAmBuildBody stamped (data-am-build-sig), never the index.html
// scaffold line. _bmLiveEmptyText is the empty Daemon Slayer row's text.
// Browser half: tests/snapshot_panels/test_ui_mock_active_match_complete.py.
import { test } from "node:test";
import assert from "node:assert/strict";

import { _amBuildPainted, _bmLiveEmptyText, _shouldRetainBuild } from "./active_match.js";

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
