# CC binary pin bump 2.1.205 → 2.1.223 — release research + out-of-repo install, 2026-08-06

Companion to the same session's flag and model_params entries in this area. Covers the parts that
happened outside the repo and the release research behind the bump decision; the in-repo change
(CLAUDE_BIN line in `src/claude_proxy_start.sh`) is a one-line commit documented in the script
itself.

## Release research (as of 2026-08-06, via GitHub releases of anthropics/claude-code)

- v2.1.205 released 2026-07-08 — was the newest stable at the time of the previous pin (the
  claude-205 wrapper's own comment: "monthly stable cadence").
- v2.1.223 released 2026-08-06 — newest stable at bump time; 18 releases between the two pins.
- `claude-opus-5` was introduced in **v2.1.219 (2026-07-24)** as the new default Opus model (1M
  context). The 205 binary therefore predates the model id entirely — the `--opus` start flag
  could not produce a correct Opus 5 system prompt on 205, which is what forced the bump beyond
  monthly cadence.
- Proxy-relevant changes found between 205 and 223 (flagged for the live verification, issue #63):
  1. 2.1.212 — prompt caching: mid-conversation system block now works behind gateways/custom
     base URLs; potential interaction with `cache.py` breakpoint placement.
  2. 2.1.212 — session transcripts record reasoning-effort level per assistant message;
     `set_model` applies mid-turn.
  3. 2.1.223 — auto-compact holds unknown model IDs within an assumed context window;
     `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` restores old behavior. Relevant
     because proxy-override model ids can look "unknown" to CC.
  - No changelog entry between 205 and 223 mentions changed background-task notice wordings —
    the strip surfaces (`strip_bg_launch_ack.py`, `strip_bg_completed.py`, TN branch) were not
    flagged as touched, but only live traffic proves it.

## Out-of-repo install (mirrors the 205 setup exactly)

- `npm install @anthropic-ai/claude-code@2.1.223` into `~/cc-cache-fix-223/` (own directory per
  pin, same pattern as the previous `~/cc-cache-fix-205/`).
- Wrapper `~/.local/bin/claude-223`: `DISABLE_AUTOUPDATER=1` + `exec` of the native Mach-O binary
  (`bin/claude.exe`) — byte-pattern identical to the 205 wrapper apart from paths/comments.
  Verified: `claude-223 --version` → `2.1.223 (Claude Code)`.
- The old `claude-205` wrapper and `~/cc-cache-fix-205/` were DELETED the same session on explicit
  user instruction — no silent fallback remains; rollback path if 2.1.223 breaks the proxy
  pipeline is a fresh `npm install @anthropic-ai/claude-code@2.1.205` (two minutes).

## Config went live mid-session

The `model_params` section (per-model thinking/effort/max_tokens, keys `claude-fable-5` /
`claude-opus-5` / `claude-sonnet-5`) was pasted into `~/.claude/shared-rules/proxy_rules.json`
directly during this session — from that moment the running proxy stopped rewriting the model
field (mtime-based config cache picks the change up without restart). Legacy
`model_override`/`model_override_worker` sections were left in the file; they are ignored while
`model_params` is present.

## Verification state at session end

Not yet live-verified (issue #63 defines the test): a full session start on the 223 binary through
the proxy — system prompt of the natively chosen model, strip wordings against 223's traffic,
cache breakpoints, dual_log integrity. The user runs this as the first action of the next session
via the usual start command plus `--opus` or `--fable`.
