# 2026-07-30 — `fn_map` attribution stays text-guessed; tracking dropped

## What the defect is

`fn_map` (`strip_inject_delta.py::_build_stripped_injected_deltas`) records, per changed location,
the strip/inject function held responsible. That name is not carried from the pass that ran — it is
re-derived afterwards from the changed text via `_attribute_chunk` → `_MSG_CODE_TO_FN`, plus one
hardcoded text test (`elif "background done" in i_text: → "_apply_bg_exit_strip"`).

Three gaps measured 2026-07-30 on six live bg wake-ups:

1. All three terminations labelled `_apply_bg_exit_strip` although the origin is
   `_apply_first_pass`'s TN branch — both paths deliberately emit the sentence the hardcoded test
   keys on, so the first test always wins. One run had exit code 0, which `_BG_EXIT_RE`
   (`strip_bg_completed.py`) explicitly excludes — proof the labelled pass cannot have fired.
2. Launch-ack replacements resolve to `unknown` — proxy-authored replacement text carries no strip
   marker by construction, so there is nothing for the guesser to key on.
3. Wake-up messages resolve to `unknown` on the stripped side although `attribute_chunk` correctly
   returns `SNP` — `_MSG_CODE_TO_FN` has no `SNP` entry.

Structural limit on top: `fn_map` holds ONE name per location key, so two passes touching the same
block collapse to one label.

## Why it was dropped rather than fixed

No consumer left that anyone looks at. The REQ-header badge was switched (2026-07-30) to plain
`strip`/`inject` words sourced from `_has_content_by_flow_id` — the delta content itself, not
`fn_map`. As of this date the only remaining readers are two one-off dev probes
(`dev/proxy_dual_log/attribution_coverage.py`, `dev/proxy_dual_log/green_overlay_probe.py`).

Cost of the real fix is disproportionate to that: carrying the pass name through `rules.py`'s pass
loop and `_merge_ops` instead of guessing it, plus widening `fn_map` to a list per location. The one
cheap piece — adding the missing `SNP` entry — is a third of the problem and would leave the guessed
attribution and the one-name-per-location limit untouched, i.e. a partially-correct column that
still cannot be trusted.

## What a future reader must not assume

`fn_map` values are a guess, not a record. Any debugging that rests on them needs to re-derive the
acting pass from the payload, or fix the carry-through first. The 2026-07-30 measurement above is
the concrete evidence that a wrong label is not hypothetical.
