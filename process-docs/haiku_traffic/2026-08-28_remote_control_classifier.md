# 2026-08-28 — Where the haiku traffic comes from, and the switch that turns it off

Opening entry of this area. Subject: the proxy pane shows haiku sidecar requests interleaved
with roughly every second opus request. The working assumption was that haiku only generates
the session title. That assumption was wrong by a factor of 43.

## Measurement

One main session's `_forwarded` dual-log (`api_requests_opus_monitor_cc_1787931850`), read by
extracting every haiku request's system blocks and message content in full:

- 45 haiku requests total.
- **43** are an agent-state classifier.
- **1** generates the session title (`<session>…</session>` plus "Write the title in deutsch").
- **1** is a quota probe: system empty, message body `quota`, `max_tokens: 1`.

Input volume across the session, accumulating the system blocks per request rather than
counting only the delta:

- system: 701,314 chars ≈ 175,000 tokens
- messages: 70,227 chars ≈ 17,500 tokens
- total ≈ **193,000 haiku input tokens**

The title call contributes 224 chars of that, roughly one three-thousandth.

## What the classifier is

Its system prompt is 16,693 chars and states its own purpose verbatim: a user "kicked off a
Claude Code agent to do a coding task and walked away"; the model reads the tail of the
assistant's last message and classifies it as `done`, `working`, `blocked` or `failed`; the
classification "drives a phone notification", where `blocked` pings the user and everything
else does not. This is the Remote Control feature's notification half.

It fires after essentially every assistant turn, carrying the full 16.7k prompt each time plus
the assistant tail as its message.

## Why the pane appeared to show two different things

The proxy pane showed `sys:83` for early haiku rows and `sys:17k` for later ones, which reads
like two different callers. It is one caller. The `_forwarded` log is a delta log: after the
first request only the changed system block — the 81-char billing header — appears in
`system_delta`. The 16.7k block is still sent on every request; the pane displays the
accumulated total, the log displays the delta.

## Finding the off switch — the detour and the shortcut

The first approach was to locate the gate in the Claude Code binary
(`claude.exe`, 272 MB, native Mach-O with an embedded minified JS bundle). The classifier
prompt and its response schema were found in plaintext; the calling code and its guard were
not, after five attempts. Extracted along the way and recorded as candidates only:
settings-shaped names `agentPushNotifEnabled`, `inputNeededNotifEnabled`,
`isRemoteControlInternalEventsEnabled`, `isUdsEnableRemoteControlEnabled`,
`isPersistentRemoteSessionEnabled`; env vars `CLAUDE_CODE_CLASSIFIER_SUMMARY`,
`CLAUDE_CODE_BG_CLASSIFIER_MODEL`, `CLAUDE_CODE_TWO_STAGE_CLASSIFIER`,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`; server-side flags `tengu_bg_classify`,
`tengu_classifier_summary_kill`, `tengu_classifier_disabled_surfaces`.

The answer came from indexing `anthropics/claude-code` issues and searching them, which took
one command. In a comment on the auto-enable thread:

```json
{ "disableRemoteControl": true }
```

in `~/.claude/settings.json`. It is a documented key in `claude-code-settings.schema.json`
shipped inside the VS Code extension, and per its own description covers claude.ai/code, the
`claude remote-control` command, the `--remote-control` / `--rc` flags, auto-start, and the
in-session toggle. Two reasons it stays undiscovered: the schema describes it as "typically set
in managed settings", so it reads as an enterprise knob although it is read from ordinary user
settings; and everyone tests the narrower `remoteControlAtStartup` instead.

The lesson is the ordering, not the finding. The conversation layer was the cheap channel and
it was tried last.

## Adjacent state on this machine

`awaySummaryEnabled: false` was already set and did not suppress the classifier — it governs
the summary, not the state classification. No `remoteControl*` key existed at all, which
matches several open reports that Remote Control auto-enables without consent. Those reports
also note that while it is connected the session transcript is stored server-side, tool
results included, which makes it a data-residency question and not only a control-channel one.

## What was changed

`~/.claude/settings.json` gained `"disableRemoteControl": true`. One key only, deliberately:
`remoteControlAtStartup` was left unset so the follow-up count has a single variable to
attribute the result to.

## Unverified

Everything downstream. The setting is read at session start, so the count has to be taken on a
fresh session: haiku requests in that session's `_forwarded` log, expected to fall to the title
call plus the quota probe. A caveat carried over from the source comment: it was not confirmed
there whether the key beats the server-side auto-enable flag at runtime, and a server flag
overriding a local setting has precedent in `process-docs/thinking/`.

## Cross-reference worth keeping

The classifier's own discriminator for `blocked` is a closing that ends on a direct question
the user must answer. The orchestrator closes most turns exactly that way, which is a known
unresolved finding recorded in `process-docs/verbosity/`. If that pattern persists, the
classifier is being fed a near-constant `blocked` signal.
