# 2026-08-29 — --only everywhere, and the overview-must-not-filter rule reversed

Eleventh entry of this area. `--only` existed for `expand --full` and was actively FORBIDDEN in
overview mode, exiting 2. That restriction is now lifted, the flag reaches `search` as well, and its
syntax grew from a bare token to role / type / role-pair.

## The reversed decision

The original rule, recorded when `expand` was built: overview mode promises every turn in the
window, so a filter would break that promise invisibly, and `--only` without `--full` exits 2. The
reasoning assumed an agent guessing at classifier names — filter for something misspelled, get a
short list, believe it.

What changed is the premise, not the argument: the skill now documents every classifier name, so
the filter is applied knowingly. Two guards keep the original concern addressed:

- an unknown token **exits 2** naming the accepted forms, instead of silently matching nothing;
- the header keeps stating the **full** window (`turns 683-743 of 0-765, anchor #713, 2026-08-28,
  only user/text`), so a narrowed listing always shows what it was narrowed from.

The `--before`/`--after` floor of 30 is untouched. Filtering narrows what is PRINTED, never the
window that was examined — which is the distinction that made lifting the rule safe.

## Syntax, and where the vocabulary came from

`--only` accepts a role (`user`), a type (`tool_result`), or a `role/type` pair (`user/text`),
case-insensitive. The pair form matters because role and type are independent: `user` covers
tool_results and task-notifications alongside genuine typing, `text` covers assistant prose
alongside user prose, and only `user/text` isolates what the human actually wrote.

The vocabulary was measured, not assumed — a sweep over 12 sessions returned exactly these pairs:

```
system/system 2116   assistant/tool_use 1710   user/tool_result 1710   user/text 387
assistant/text 249   assistant/thinking 249    user/task-notification 111
user/system-reminder 12
```

`command-message` is in `message_summary`'s classifier source but absent from the sampled corpus; it
is listed as accepted anyway, since the vocabulary should follow the producer rather than one
sample.

## One definition, three call sites

`classifier.py` holds `ROLES`, `TYPES`, `parse_only` (spec → `(role, type)` pair, or
`BadClassifierError`) and `matches_only`. `expand` overview, `expand --full` and `search` all route
through it, and `ONLY_FORMS` — the accepted-forms sentence — is interpolated into both `--help`
texts so the syntax is documented at the point of use rather than in prose that can drift.

Threading it into `search` needed one plumbing change: `iter_block_texts` now also yields the
turn's message `type`, so hits can be filtered by the same message-level classifier `expand` uses
instead of by their block label. Without that, `search --only text` would have meant "block of type
text" while `expand --only text` meant "message of type text" — the same flag with two meanings.

## Verification

- `expand … 713 --only user/text` → 6 lines (695, 707, 710, 713, 722, 731) with times, header
  still naming the full 683-743 window.
- `search "Reißleine" websearch --since/--until 2026-08-28 --only user/text` → 2 hits, down from 16
  unfiltered; the removed 14 were the assistant quoting the word and tool results listing the issue
  title, which is exactly the noise the filter exists to drop.
- Forms: `--only user` 21 lines, `--only TOOL_RESULT` 13, `--only Assistant/Thinking` 5,
  `--only task-notification` 2 — case-insensitivity confirmed on all three shapes.
- Rejections (rc=2): `nonsense`, `user/nonsense`, `nonsense/text`, `user/`, and the reversed pair
  `tool_use/user`.
- `expand --full --only user/text` unchanged in behaviour; a filter with no match prints
  `no turn in the window matches --only command-message`.
- Corpus smoke: 61 sessions, `worker-cli` restricted to `user/text` → 6 hits, no exceptions.

## A near-miss worth recording

The scripted edit that added the parse-and-validate block to `_run_search` also matched
`_run_sessions`, which opens with the same `_reject_bad_days` + `filter_sessions` shape. `sessions`
has no `--only` flag, so every invocation would have died with `AttributeError` on `args.only`. It
was caught by running `sessions` immediately after patching, not by reading the diff. A structural
find-and-replace matches by shape, and two commands sharing a preamble is exactly the shape
collision that does not announce itself.
