# REQ-Header Badge: Numeric `Nstrip Ninj` → Plain `strip`/`inject` Words

## Symptom (as of 2026-07-30)

The proxy pane's REQ-header badge showed `{n}strip {n}inj`, where `n` = count of DISTINCT
function names in that request's `fn_map` (attribution dict written by
`strip_inject_delta.py`). Two problems observed on the recorded session
`api_requests_opus_monitor_cc_1785364138`:

1. The count had no user-facing meaning — two locations touched by one pass render `1strip`,
   seventeen locations touched by six passes also render `6strip`. Neither number answers a
   question a user would ask.
2. Header/expanded-view disagreement on `"."`-filler injections. When a text block is emptied
   entirely (e.g. `_apply_role_system_strip` nuking a `role='system'` block), the API rejects an
   empty text block, so the delta writer injects a literal `"."` filler. `_process_messages_section`
   in `strip_inject_delta.py` (around the `if i_text == ".": pass` branch) deliberately skips
   `fn_map` attribution for this case — by design, since it's not a real content injection to
   attribute to a pass. Concrete case: request `0eaf06ba…` (dual-log line for msg-index 84,
   `flow_id=508cabc1-7113-45f1-9ce8-44d0616a943e`) had `fn_map` empty on the injected side but
   `messages_delta={"84": {"0": [...]}}` non-empty — the expanded view rendered a green
   (injected) span for that block while the header showed no `inj` badge at all.

## Root Cause

The badge (`render_turn._build_req_header_line`) and the accumulator that feeds it
(`parser.accumulate_dual_log`'s `_fns_by_flow_id`) both derived their signal from `fn_map`.
`fn_map` is an attribution map (which function is responsible), not a presence signal, and it
is intentionally sparse — the `"."`-filler case is excluded by design because no pass
"caused" that content in the attributable sense. Using it as a presence check conflated two
different questions ("did anything change" vs "who is responsible").

## Fix

Moved the presence signal off `fn_map` onto the delta payload itself. Each dual-log line
(`stripped_delta` / `injected_delta`) already carries `system_delta` / `tools_delta` /
`messages_delta` / `fields_delta` — non-empty exactly when that section changed for THIS
request (hash-diffed against the previous request server-side, in `strip_inject_delta.py`,
untouched by this fix). `accumulate_dual_log` (`parser.py`) now computes, per JSONL line:

```python
has_content = bool(entry.get('system_delta') or entry.get('tools_delta')
                    or entry.get('messages_delta') or entry.get('fields_delta'))
```

stored per `flow_id` in a renamed accumulator key `_has_content_by_flow_id` (was
`_fns_by_flow_id: {flow_id -> set(fn_names)}`, now `{flow_id -> bool}`). The `"."`-filler case
populates `messages_delta` (the block WAS injected, just its text is `"."`) even though
`fn_map` stays empty for it — so the new signal agrees with what the expanded view renders,
closing the header/expanded-view disagreement.

`render_turn._build_req_header_line` reads the two booleans (`entry['_strip_fns_lookup']` /
`entry['_inject_fns_lookup']`, attribute names on the entry left unchanged — only what they
point at changed) and renders plain `strip` (YELLOW) / `inject` (GREEN) words, no count, each
shown independently when its bool is True.

`fn_map` itself, and everything writing it in `src/proxy/`, is untouched — `fn_map` still feeds
`dev/proxy_dual_log/attribution_coverage.py` and `dev/proxy_dual_log/green_overlay_probe.py`
unchanged.

## Verification (as of 2026-07-30)

Dev probe `dev/proxy_instrumentation/p2_badge_words_probe.py` drives the real
`accumulate_dual_log` → entry-attach → `_build_req_header_line` path over two recorded
sessions (`api_requests_opus_monitor_cc_1785364138`, `api_requests_opus_monitor_cc_1785347492`
— the latter needed because no strip-only request without an accompanying injection exists in
the 1785364138 session; every strip in that session co-occurs with an injection). 4/4 cases
matched:

| case | request_id prefix | rendered badge |
|---|---|---|
| `.`-filler injection (msg 84, `_apply_role_system_strip`) | `0eaf06ba` | `strip inject` |
| bg wake-up replacement (msg 52) | `2ae188e7` | `strip inject` |
| strip present, no injection | `ca01cd43` | `strip` |
| neither | `daadb2b0` | none |

Colors confirmed unchanged at the raw-ANSI level (`YELLOW`/`GREEN` from `constants.py`,
`38;2;249;226;175` / `38;2;166;227;161` respectively).

Regression coverage: `dev/proxy_dual_log/A_render_refactor_proof.py` (14 synthetic cases,
byte-identical against a pre-fix baseline — none of its fixtures populate
`_strip_fns_lookup`/`_inject_fns_lookup`, so this proves no unrelated rendering drift, not
badge coverage) and `dev/proxy_dual_log/test_composition_invariant.py` (12/12) both passed
unchanged. `dev/display/test_hover_map.py` failed on `ImportError: _parse_log_file` both
before and after this change (confirmed via stash-compare) — pre-existing breakage, unrelated
to the badge, left untouched.
