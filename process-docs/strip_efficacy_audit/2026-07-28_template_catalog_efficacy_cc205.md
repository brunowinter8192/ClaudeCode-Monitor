# Strip-Template Efficacy Under CC 2.1.205 — Measured 2026-07-28

Driving question: of the 11 `_SR_TEMPLATES` in `src/proxy/strip_sr.py`, which still fire against real
traffic, and which are candidates for retirement? Outcome as of this session: **no template retired** —
the measurement showed the catalog is not dead but *shadowed* by an upstream pass, and the corpus was
too thin (3 sessions, 0 worker logs) to justify deletions.

## Result — all 11 SR templates: 0 fires

Replay over `src/logs/dual_log/*_original.jsonl` (3 sessions, 534 request entries, 1400 messages after
full-content dedup): every one of the 11 templates matched **zero** SR-wrapped blocks.

The template texts are not gone from the traffic — 60 of them are present. CC 2.1.205 no longer
delivers them wrapped in `<system-reminder>` inside a `user` message; it sends them as standalone
`role: "system"` messages with bare text. `_apply_role_system_strip` (pass #1 in `rules.py:_passes`)
replaces the entire content of every such message with `"."`, so nothing SR-shaped ever reaches
`_apply_first_pass` / `_apply_cumulative_sr_strips` / `_apply_final_sr_pass`.

Measured `modifications[]` over the cumulative history of each session:

| modification | count |
|---|---|
| `stripped_role_system_msg` | 60 |
| `stripped_hook_error_prefix` | 3 |
| `stripped_po_preview` | 2 |
| `stripped_all_sr_msg0` / `stripped_all_sr` | 1 / 1 |
| `stripped_git_lock_advice` | 1 |

17 rule names in `strip_vocab.RULES` produced no `modifications[]` entry at all in this corpus.

## Shadowed ≠ dead — the discriminating probe

A rule with 0 fires has three possible causes, and they must not be collapsed:

1. **dead** — CC no longer emits the trigger shape at all
2. **shadowed** — an earlier pass consumes the content before this rule is reached
3. **absent condition** — the state that triggers it never occurred in the corpus

Discriminator used: run the pass list twice over the same payloads, once complete and once with
`_apply_role_system_strip` removed. With RS: 60 chunks, all attributed to it. Without RS: 0 — the
templates still do not fire, because without the SR wrapper their `startswith` identifier match cannot
hit. That isolates cause 2 for the affected templates: the content is consumed upstream, and the
template layer would not catch it even if it were reached.

## Attribution reports fires that never happened

`strip_vocab.attribute_chunk` maps a removed chunk to a rule code by marker substring, with **no
knowledge of which pass removed it**. Running it over the 60 RS-pass chunks yields:

`NAG` 53, `DEF` 3, `FM` 2, `UI` 1, `CMD` 1 — i.e. the bookkeeping credits five SR templates with
fires they never made. Total attributed across all passes: 68 chunks, 0 unattributed.

Consequence for any efficacy audit: **counting rule codes from the logs measures the attribution
layer, not the execution layer.** A per-rule fire count must come from replaying passes in isolation
against unmodified payloads, never from `fn_map` / chunk-code aggregation.

## Marker collision scan

Cross-product over all `RULES` markers for substring containment found exactly one pair:
`SN`'s `'[SYSTEM NOTIFICATION'` is a substring of `SNP`'s marker. Already handled by the `startswith`
special-case at the top of `attribute_chunk`. No second collision exists in the current catalog.

## Per-template status after user classification

| Template | Status | Basis |
|---|---|---|
| task-tools-nag | shadowed by RS (53 chunks) | measured |
| deferred-tools | shadowed by RS (3) | measured |
| file-modified | shadowed by RS (2) | measured |
| user-interrupt | shadowed by RS (1) | measured |
| claudemd-contents | shadowed by RS (1) | measured |
| system-notification | superseded by `strip_sn_notice.py` (bare paragraph) | prior session |
| date-changed | present in corpus as role=system head | measured |
| skills-available | CC no longer sends the description block; Skill tool itself works | user, screenshot of forwarded tool defs |
| agent-types | Agent tool disabled by config → CC never emits the list | user |
| plan-mode | user-invoked only, never activated in practice | user |
| pyright-diagnostics | unevaluable — fires on code edits, i.e. worker sessions; 0 worker logs in corpus | measured absence |

## Preserve guards verified live

- CLAUDE.md context block: 2 occurrences, still SR-wrapped, correctly preserved by `_PRESERVE_PREAMBLE`.
- Env-context SR (userEmail/currentDate): 2 occurrences, correctly stripped by `_ENV_CONTEXT_RE`,
  which runs *before* the preamble guard. Both mechanisms unaffected by the shape change.

## Why the corpus is 3 sessions

`claude_proxy_start.sh:_janitor_version_purge_jsonl_logs` hashes all proxy sources; on any change it
deletes every dual-log older than 60 min. The nominal count-30 rotation (30 opus + 30 worker) never
gets to apply while the proxy is under active development. A strip change the previous evening emptied
the window. Worker sessions (`api_requests_worker_*`) rotate separately — 0 present, which is exactly
why pyright cannot be assessed.

## External corroboration

Three independent lines agree that the delivery shape changed, not the content:

- **anthropics/claude-code#77698** (CC 2.1.208, third-party proxy capture): harness context is sent as
  `{"role": "system"}` appended *after* the user turn, on every request incl. the first of a session.
  States the agent-types list and the skills list are the two variants — disallowing the Agent tool
  swaps which one is injected. Per Anthropic docs cited there, mid-conversation system messages are
  supported on one recent model only, with a documented fallback to `<system-reminder>` in the user
  turn; CC does not gate on it.
- **r/LocalLLaMA** (`1tqiewb`): CC ≥ 2.1.154 introduced the roles `ctx`, `msg` and `system` in
  `messages[]`; a vLLM role-literal patch was needed. Dates the change.
- **r/ClaudeCode** (`1s7mitf`, binary RE + MITM): `deferred_tools_delta` attachment (since 2.1.69)
  carries deferred tools + MCP instructions + skills list, positioned at `messages[0]` on fresh
  sessions and at `messages[N]` on resume — the shape and position are session-state dependent.

Role inventory over our own corpus: `user` 79441, `system` 10653, `assistant` 78855. No `ctx` / `msg`
in this window; per user, these role names are the CC-internal tag family and get renamed frequently —
all of them are visible to the proxy, so this is a naming-churn surface, not a blind spot.

## Decision — no retirement

Rejected retiring any template this session. Reasons, in order of weight:

1. Seven of eleven are shadowed, not dead. Their trigger shape is documented upstream as
   model-dependent with a fallback to the old wrapper — deleting them bets on the wrapper never
   returning.
2. The remaining four are decided by configuration (Agent tool off, plan mode unused, skills
   description dropped by CC) or unevaluable (pyright, no worker logs). None needs a code change to
   stay safe.
3. Risk/benefit: at most a handful of concretely retirable functions against a corpus of 3 sessions
   with no worker coverage.

Also deliberately not done: rewiring the template layer to run on `role: "system"` messages. It would
make the rules fire visibly and align bookkeeping with execution, but it is a behavior change on the
live strip path justified only once a broader corpus exists.

## Artifacts

Probes for this session were one-shot inline scripts, not committed. The reusable audit tooling was
deferred with the retirement decision.
