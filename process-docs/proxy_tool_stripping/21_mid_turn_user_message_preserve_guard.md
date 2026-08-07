# 21 — Mid-Turn User Message Preserve-Guard (issue #61, CC 2.1.223)

## Symptom

CC 2.1.223 delivers a mid-turn user message — a user typing while the session is working, AND
`worker-cli send` to a working worker (same delivery mechanism) — as a `role='system'` MESSAGE in
the messages list, body starting with `"The user sent a new message while you were working:"`
followed by the user's text and a CC boilerplate explainer. `_apply_role_system_strip`
(`message_passes.py`, pass 1 — purely structural `role=='system'` → `"."`) nuked it entirely, so
the user's own text NEVER reached the model.

Live evidence: recorded session `src/logs/dual_log/api_requests_opus_posts_1786051932_*`, stripped
delta `msg.274.0`, `fn_map` = `_apply_role_system_strip`. Original body: `"The user sent a new
message while you were working:\njetzt\n\n..."` — the user's message was the single word "jetzt",
completely dropped before reaching the model.

## Historical context

Pre-223, this exact content arrived as a `role='user'` `<system-reminder>` block —
`strip_sr.py`'s `'user-interrupt'` template (`"The user sent a new message while you were
working:"`, mode `'partial'`): only the `IMPORTANT:` line is stripped, the user's body is
preserved inside the SR wrapper. The 2.1.223 role=system delivery form bypasses that SR-based
guard entirely, since `_apply_role_system_strip` runs unconditionally on ANY `role='system'`
message regardless of its content — it has no SR-tag dependency to hook into.

`_apply_role_system_strip` already had two precedent preserve-guards for exactly this class of
problem (a structural role-based nuke accidentally catching content it should not): the
`_TRUNCATION_NOTICE_MARKER` guard (`"[Truncated:"`, CC 2.1.205+ Read-partial notices) and the
`<task-notification>`-tag guard (CC's bg-task wake-ups delivered as role=system on some paths).

## Fix

Third guard, same placement/style as the existing two: `_MID_TURN_USER_MSG_MARKER = "The user
sent a new message while you were working:"`; inside the loop,
`if isinstance(old_content, str) and old_content.lstrip().startswith(_MID_TURN_USER_MSG_MARKER):
result.append(msg); continue`. Whole-message preserve, not a partial trim like the SR-era
`'partial'` mode — deliberately simpler: losing the user's text is the actual failure mode this
closes, the few extra lines of CC's own boilerplate explainer are harmless noise by comparison,
and a partial-trim implementation would need to track/strip that boilerplate tail precisely for
no real benefit.

**RS-attribution check (explicitly investigated, no change made):** `strip_inject_delta.py`'s
`'RS'` code path only runs inside `if s_texts:` — i.e. only when `compose_block` actually finds a
stripped span for that message. Since the preserved message is now byte-identical
original→forwarded, no span exists, `s_texts` is empty, and the whole attribution branch never
executes for it. The message produces no delta at all — confirmed this is exactly "simply seeing
no change", no code adjustment needed in `strip_inject_delta.py`.

## Verification (as of 2026-08-07)

New probe `dev/proxy_instrumentation/p5_mid_turn_user_msg_preserve_probe.py` drives the real
`_apply_role_system_strip` on real recorded message lists (not synthetic fixtures) from two
sessions. 4/4 checks: msg 274 of the incident flow (`api_requests_opus_posts_1786051932`,
flow `4b4d396b...`) survives byte-for-byte, containing `"jetzt"`, not recorded in
`changed_indices`; three unrelated `role='system'` noise messages from
`api_requests_opus_websearch_1786052022` (deferred-tools list at msg 1, task-tools nag at msg 33,
date-changed notice at msg 49) all still strip to `"."` exactly as before — confirms the guard is
narrowly scoped to its one marker, not a general widening.

`dev/proxy/test_strip_fix.py` extended (150 → 159 checks, 9 new): a synthetic test using the
EXACT recorded msg-274 body, verifying untouched content, `'jetzt'` presence, role preservation,
no mod/removed/ops recorded for the message index, plus a leading-whitespace variant confirming
the guard checks `lstrip()`'d text rather than an exact prefix match. Full suite: 159/159 pass.
`dev/proxy_dual_log/test_composition_invariant.py` (12/12) reran unchanged, confirming no
unrelated composition drift.
