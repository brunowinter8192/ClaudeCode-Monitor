# Env-context system-reminder strips again on CC 2.1.258 (2026-09)

**Topic:** `_ENV_CONTEXT_RE` in `src/proxy/strip_sr.py` widened so the userEmail/currentDate
system-reminder CC injects on nearly every request keeps stripping under CC 2.1.258, which
appends two extra sentences after the email address.

## Problem

CC 2.1.258 changed the userEmail line from a single sentence to three:

```
The user's email address is brunowinter7934@gmail.com. Use it only to identify the user, such as
for authorship, attribution, or filtering their own work. Never send it to an unrelated service,
such as in a request header, URL, or payload, unless the user explicitly asks.
```

`_ENV_CONTEXT_RE` (added 2026-05-30, see `task_2026-05-30.md` in this area) required `\n`
immediately after `gmail\.com\.` — the fullmatch failed on the new form, the `_ENV_CONTEXT_RE`
pre-guard never fired, and the block fell through to `_PRESERVE_PREAMBLE` (which it shares a
preamble with) and was preserved whole — reaching the API in message 0 of every session.

## Measurement first

Scanned every `src/logs/dual_log/*_original.jsonl` in the main checkout (14 files, 2888 request
entries at measurement time) for every top-level standalone `<system-reminder>` block whose inner
text contains `# userEmail`, deduplicated by (file, exact inner text) since dual-logs are
cumulative snapshots and the same block reappears in every later request of a growing session.
Five distinct normalized forms surfaced on a first, naive (structure-recursive, no anchor)
pass; re-measuring with the SAME traversal `_strip_system_reminders` actually uses (top-level
`str`/`list[type=='text']` only, `_STANDALONE_SR_RE`'s `^`-anchor, never `tool_result`) collapsed
that to 3 forms that the regex can ever be asked to match, plus 2 the recursive pass had wrongly
surfaced:

1. **Pre-2.1.258 form** (1866 raw occurrences, deduplicated to 7 distinct blocks) — the exact
   2026-05-30 shape, single-sentence email line.
2. **CC 2.1.258 form** (699 raw, deduplicated across before/after into the same distinct-block
   pool) — the 3-sentence email line, the form this task fixes.
3. **Bundled `# claudeMd` + `# userEmail` form** (242 raw, 3 distinct blocks) — CC sometimes
   delivers the CLAUDE.md project-context block AND the userEmail/currentDate block concatenated
   into ONE `<system-reminder>` wrapper rather than two separate ones. Genuinely new — not
   mentioned in the 2026-05-30 or 2026-07-28 entries in this area, both of which only ever
   observed the two blocks arriving separately.
4. **Discarded — not `^`-anchored, not a real CC injection** (12 raw): a `role='user'` message
   where the USER pasted/quoted the literal env-context text (with 8-space indentation and an
   ellipsis-truncated middle sentence, "Never send it to …") while asking a question about the
   proxy's strip behavior. `<system-reminder>` sits mid-line (`...eigneltcih <system-reminder>...`),
   so `_STANDALONE_SR_RE`'s `^`-anchor never matches it regardless of the regex change — confirmed
   this is genuinely inert to the fix, not merely unlikely to matter.
5. **Discarded — inside `tool_result`, never reached** (26 raw, both old- and new-form text):
   RAG/doc-search results quoting the env-context block as a documentation example (same FP-nuke
   class as the "Occurrence-8" fixture in `dev/proxy/test_strip_fix.py`'s T37). `_strip_system_reminders`
   never descends into `tool_result` (2026-07-28 fix), so this text is never handed to
   `_ENV_CONTEXT_RE` at all.

Only forms 1 and 2 are inputs the fix must handle; form 3 must continue to NOT match (see below);
forms 4 and 5 are structurally out of the regex's reach either way.

## The fix

```python
r"The user's email address is brunowinter7934@gmail\.com\.[^\n]*\n"
```

replacing the old

```python
r"The user's email address is brunowinter7934@gmail\.com\.\n"
```

`[^\n]*` tolerates any trailing text on the SAME line as the email sentence (zero chars for the
pre-2.1.258 form, the two new sentences for 2.1.258) without touching any other anchor — the
preamble line, `# userEmail`, `# currentDate`, the date regex, the `\s+` gap, and the IMPORTANT
footer are all unchanged literal/regex text. Verified both forms `fullmatch` after the change and
250 pre-existing `dev/proxy/test_strip_fix.py` checks still pass unmodified.

**Form 3 (bundled) is correctly left untouched by this fix, not a residual bug.** Its inner text
is not JUST the env-context block — real CLAUDE.md project content sits before the `# userEmail`
line inside the SAME block — so `_ENV_CONTEXT_RE.fullmatch` correctly fails and the block falls
through to `_PRESERVE_PREAMBLE`, which is exactly right: losing the CLAUDE.md content to strip
~250–550 bytes of env-context noise would be a worse trade than leaving it. No mechanism exists in
this task's scope to partial-strip inside an otherwise-preserved block, and building one was not
asked for — pinned as `T44` in `test_strip_fix.py` and tracked separately in the replay probe's
`left-BUNDLED` bucket precisely so a future reader does not "fix" it as an oversight.

## Tests added

`dev/proxy/test_strip_fix.py` T40–T44 (250 → 255 checks): T40 May-2026 form strips, T41 CC 2.1.258
form strips, T42 a CLAUDE.md context block (different body, same preamble) is preserved, T43 an
env-context-shaped block with a DIFFERENT email is preserved (the email is a hardcoded literal
specific to this proxy's own user, by design — matches only the one email this proxy ever sees),
T44 the real bundled-form fixture is preserved whole.

## Replay

New `dev/proxy/replay_env_context_strip.py` — classifies every distinct top-level env-context-
shaped block against both the OLD (quoted verbatim in-script) and the live `_ENV_CONTEXT_RE`, into
4 buckets: stripped, left-PURE (genuinely broken — the bug), left-BUNDLED (form 3, preserved by
design), CLAUDE.md-preserved (no userEmail hint at all). As of this task, over the corpus
described above:

| Bucket | Before | After |
|---|---|---|
| stripped | 7 | 10 |
| left — PURE (the bug) | 3 | 0 |
| left — BUNDLED (by design) | 3 | 3 |
| CLAUDE.md-preserved, no userEmail hint | 0 | 0 |

The 3 newly-stripped blocks are exactly the CC 2.1.258 form. The BUNDLED bucket is unchanged
before/after, as it must be. The CLAUDE.md-preserved bucket reads 0/0 in this corpus window — a
property of which sessions happen to sit in the current rotating `dual_log/` window (14 files at
measurement time), not evidence the `_PRESERVE_PREAMBLE` guard stopped firing; the 2026-07-28
entry in `process-docs/strip_efficacy_audit/` measured 2 such occurrences in a different, earlier
corpus window, and this task did not touch that guard or its position at all.

## What was not touched

`_PRESERVE_PREAMBLE` and its position (checked before template dispatch, and `_ENV_CONTEXT_RE`
checked before `_PRESERVE_PREAMBLE` — both pre-existing orderings, both load-bearing per
`task_2026-05-30.md`) are unchanged. No other `_SR_TEMPLATES` entry was touched.
`strip_vocab.py`'s `'ENV'` rule marker (`"As you answer the user's questions, you can use the
following context:\n# userEmail"`) needed no change — it is a substring check against the
PREAMBLE, unaffected by what happens later in the block.
