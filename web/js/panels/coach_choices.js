// A/B tutoring coach choice block.
//
// Reads state.coach.choices (an array stamped server-side by
// core.coach_choices.parse_choices + synthesize_simple_choices) and
// paints 2-3 chip buttons under #rn-immediate. Each chip carries:
// - the option label (Contest / Concede / Engage / Disengage / etc)
// - confidence band (low / mid / high) rendered as a 3-segment bar
// - source-tag pill (synth / archetype_sim / winrate_hist / etc)
// On click: POST /api/coach-choice with the selection + a tiny game
// context snapshot, log-only on the server; chip visually marks selected.
//
// When state.coach.choices is empty or absent, the mount is hidden +
// no DOM is generated. The existing prose stream (action / immediate /
// kv rows) is untouched.

const MOUNT_ID = "rn-choices";

let _lastSig = "";
let _lastSelectedKey = null;

function _chipsSignature(choices) {
  if (!Array.isArray(choices) || choices.length === 0) return "";
  return choices.map((c) => `${c.key}:${c.label}:${c.confidence}:${c.source_tag || ""}`).join("|");
}

function _bandDots(band) {
  const total = 3;
  const filled = band === "high" ? 3 : band === "low" ? 1 : 2;
  let html = "";
  for (let i = 0; i < total; i++) {
    html += `<span class="rc-band-dot${i < filled ? " filled" : ""}"></span>`;
  }
  return `<span class="rc-band rc-band-${band}" title="confidence: ${band}">${html}</span>`;
}

function _chipHtml(c) {
  const k = (c.key || "?").slice(0, 1);
  const label = (c.label || "").slice(0, 80);
  const outcome = (c.expected_outcome || "").slice(0, 160);
  const src = (c.source_tag || "").slice(0, 32);
  const srcPill = src ? `<span class="rc-src">${src}</span>` : "";
  return `
    <button type="button" class="rc-chip" data-key="${k}" data-label="${label}"
            data-confidence="${c.confidence}" data-source="${src}"
            title="${outcome.replace(/"/g, "&quot;")}">
      <span class="rc-key">${k}</span>
      <span class="rc-label">${label}</span>
      ${_bandDots(c.confidence)}
      ${srcPill}
    </button>`;
}

function _gameContextSnapshot(state) {
  const coach = (state && state.coach) || {};
  const lc = (state && state.liveclient) || {};
  return {
    mode_key:     state ? state.mode_key : "",
    champion:     coach.champion || lc.champion || "",
    level:        lc.level || coach.level || 0,
    game_time_s:  lc.game_time_s || coach.game_time_s || 0,
    kda:          coach.kda || lc.kda || "",
    cs:           coach.cs || lc.cs || 0,
  };
}

async function _postSelection(chip, state) {
  const body = {
    choice_key:    chip.dataset.key,
    choice_label:  chip.dataset.label,
    confidence:    chip.dataset.confidence,
    source_tag:    chip.dataset.source,
    game_context:  _gameContextSnapshot(state),
  };
  try {
    const r = await fetch("/api/coach-choice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      console.warn("coach-choice POST failed:", r.status);
    }
  } catch (e) {
    console.warn("coach-choice POST error:", e);
  }
}

export function renderCoachChoices(state) {
  const mount = document.getElementById(MOUNT_ID);
  if (!mount) return;
  const coach = (state && state.coach) || {};
  const choices = Array.isArray(coach.choices) ? coach.choices : [];
  const sig = _chipsSignature(choices);
  if (choices.length === 0) {
    if (_lastSig !== "") {
      mount.innerHTML = "";
      mount.hidden = true;
      _lastSig = "";
      _lastSelectedKey = null;
    }
    return;
  }
  if (sig === _lastSig) return;
  _lastSig = sig;
  _lastSelectedKey = null;
  mount.hidden = false;
  mount.innerHTML = choices.map(_chipHtml).join("");
  mount.querySelectorAll(".rc-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      if (_lastSelectedKey === chip.dataset.key) return;
      _lastSelectedKey = chip.dataset.key;
      mount.querySelectorAll(".rc-chip").forEach((c) => c.classList.toggle(
        "rc-selected", c.dataset.key === _lastSelectedKey));
      _postSelection(chip, state);
    });
  });
}

// Test seam.
export const _internals = {
  _chipsSignature,
  _bandDots,
  _chipHtml,
  _gameContextSnapshot,
  MOUNT_ID,
};
