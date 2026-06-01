"""One-shot migration: serialize the hand-authored cc_conditional registry to JSON.

ENGINE A3 refactor (item 245). The ~3300-line Python builders in
``agents/daemon_slayer/cc_conditional.py`` are replaced by JSON loaders;
this tool produced the data file ``agents/daemon_slayer/cc_conditional_registry.json``
ONCE from the live registry before the builders were converted to loaders.

It serializes every ConditionalCcEntry via ``dataclasses.asdict``. The
``probability`` field captured is the SEED midpoint: the tool ASSERTS the
per-entry calibration overrides are empty before running, so no operator
override is baked into the committed data (the loader re-applies
``_p`` / ``_p_form`` at load time, preserving the calibration layer).

After migration this tool is a no-longer-runnable historical artifact (the
builders it imports are gone). New conditional-CC entries are hand-added to
the JSON; the dataclass ``__post_init__`` still validates them at load.

  python tools/ds_cc_conditional_to_json.py            # write the data file
  python tools/ds_cc_conditional_to_json.py --check     # compare vs on-disk (drift guard)
"""
import argparse
import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.daemon_slayer import cc_conditional as c  # noqa: E402

_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "daemon_slayer", "cc_conditional_registry.json",
)

_NOTE = (
    "Hand-authored conditional-CC registry. Probabilities are SEED midpoints; "
    "the cc_conditional loader re-applies per-entry calibration overrides from "
    "data/cc_conditional_calibration.json (gitignored) via _p / _p_form. Do NOT "
    "bake an override into this file. Add new entries by hand (the dataclass "
    "__post_init__ validates spell/probability/durations/condition at load); the "
    "REJECT rationale + wave history live in CC_CONDITIONAL_NOTES.md."
)


def build_payload() -> dict:
    # Refuse to bake operator overrides into committed data.
    if c._PER_ENTRY_PROBABILITY_OVERRIDES or c._PER_FORM_ENTRY_PROBABILITY_OVERRIDES:
        raise SystemExit(
            "refusing to serialize with active per-entry overrides; the seed "
            "values would be clobbered. Remove data/cc_conditional_calibration.json "
            "and re-run."
        )
    primary = []
    for champ, spells in c._build_per_spell_cc_conditional().items():
        for _spell, entry in spells.items():
            primary.append(dataclasses.asdict(entry))
    forms = []
    for champ, slots in c._build_per_spell_cc_conditional_forms().items():
        for (_spell, _fi), entry in slots.items():
            forms.append(dataclasses.asdict(entry))
    primary.sort(key=lambda d: (d["champion"], d["spell"]))
    forms.sort(key=lambda d: (d["champion"], d["spell"], d["form_index"]))
    return {
        "_schema": "cc_conditional_registry_v1",
        "_generated_by": "tools/ds_cc_conditional_to_json.py",
        "_note": _NOTE,
        "primary": primary,
        "forms": forms,
    }


def render(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare vs on-disk, exit 1 on drift")
    args = ap.parse_args()
    text = render(build_payload())
    if args.check:
        try:
            on_disk = open(_OUT, encoding="utf-8").read()
        except FileNotFoundError:
            print("MISSING", _OUT)
            return 1
        if on_disk != text:
            print("DRIFT", _OUT)
            return 1
        print("OK", _OUT)
        return 0
    with open(_OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("WROTE", _OUT, len(text), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
