# 2026-07-28 — Strip/inject spans present in dual-log but not rendered in the proxy pane

## Observation

Live session `api_requests_opus_posts_1785266871` (Posts project, opus-4-8). Request #131 (dual-log line 133, 278 msgs, 22:10:29) carries a background-task completion notification at message index 276 that the proxy replaced.

The proxy pane rendered message 276 as plain, uncolored text:

```
[276] user  text                     179c
      background done — check worker or other process
      Output: <path>/tasks/bgyxceo7b.output
```

Expected: the removed original in the yellow strip highlight, the replacement text in the green inject highlight. Neither highlight appeared. The neighbouring message 274 in the same pane DID render its yellow strip span correctly.

## Data is present on disk

Both dual-log deltas exist for the same request and the same coordinate `msg.276.0`:

`..._stripped.jsonl` line 133 — `request_id b6e4f411-74b2-4b56-8940-bf5ce51e7380`:
```json
"messages_delta": {"276": {"0": ["[SYSTEM NOTIFICATION - NOT USER INPUT]\n… <task-notification>…bgyxceo7b…"]}}
```

`..._injected.jsonl` line 133 — same `request_id`:
```json
"messages_delta": {"276": {"0": [["injected", "background done — check worker or other process\nOutput: …/bgyxceo7b.output\n"]]},
                   "277": {"0": [["injected", "."]]}},
"fn_map": {"msg.276.0": "_apply_bg_exit_strip…"}
```

So the strip ran, the injection ran, the attribution (`fn_map`) is recorded. Only the pane rendering is missing.

## Size context

Original message 276 in `..._original.jsonl` line 133: 886 chars (494-char SYSTEM-NOTIFICATION header + 392-char `<task-notification>` block). Post-strip: 179 chars. Reduction ≈ 80%.

## Candidate causes (untested hypotheses)

1. **Span lookup key mismatch in `proxy_display/render_messages.py:79`** — `entry['_injected_spans']['messages'].get(str(msg_idx), {}).get(str(bidx))` returns empty for 276 although the accumulator holds it. Would explain both the missing green and the missing yellow if the same lookup pattern backs the stripped side.
2. **Per-request association via `flow_id` / `request_id`** — pane accumulates dual-log entries per `model_family` (`proxy_display/pane.py:302-313`). If the entry attached to the rendered request is a different one than the delta's `request_id`, both spans resolve empty.

Not yet examined: `forwarded_parser.py:113`, where `_stripped_spans` / `_injected_spans` are attached.

## Note on `strip_bg_completed.py`

`_BG_EXIT_RE` matches only exit codes 143/137, explicitly excluding exit code 0. The replaced notification here was `Background command "Index issues broad pass" completed (exit code 0)`. `fn_map` names `_apply_bg_exit_strip…` as the acting function, so either a second strip path handles exit-0 task-notifications or the attribution is imprecise. Worth confirming while touching this area — it does not affect the rendering defect itself.
