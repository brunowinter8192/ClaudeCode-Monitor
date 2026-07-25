# Claude Code Env-Var Inventory — v2.1.121

**Bead:** Monitor_CC-t1i, Sub-question 1
**Date:** 2026-04-28
**Binary:** `@anthropic-ai/claude-code-darwin-arm64@2.1.121` (Mach-O arm64, 205 MB)

---

## 1. Source + Methodology

### Binary Version

```
npm view @anthropic-ai/claude-code version  →  2.1.121  (latest as of 2026-04-28)
```

No newer release since the first research pass. Binary still in `/tmp/package/claude`.

### Extraction

```bash
# Step 1 — all CLAUDE_* strings
grep -oa "CLAUDE_[A-Z][A-Z_]*" /tmp/package/claude | sort -u  →  291 strings

# Step 2 — perf-adjacent non-CLAUDE_ strings
grep -oa "API_TIMEOUT_MS|ANTHROPIC_[A-Z][A-Z_]*|FALLBACK_FOR_[A-Z_]*|USE_API_[A-Z_]*" \
     /tmp/package/claude | sort -u  →  52 strings
```

### Confirmed-Read Criterion

| Tier | Definition |
|---|---|
| ✅ Confirmed | Appears in `thepono1/INSIGHTS.md` (v2.1.88 TS source extract) OR in `alanisme/claude-code-decompiled` docs OR via #33949 empirical reverse-engineering |
| ⚠️ Post-leak | In the binary, NOT in the v2.1.88 source — likely added after the source-map leak (Apr 2026). Read-site not directly verified, but the name pattern is unambiguously a functional env var (not a partial string). |
| 🔤 Fragment | Pattern prefix in the binary (e.g. `CLAUDE_CODE_DISABLE_` without suffix) — dynamically concatenated into full var names at runtime. Not a standalone var name. |

---

## 2. Env-Vars — Latency / Stream / Retry

*Direct impact on TTFB, stream stalls, timeout behavior, retry logic.*

| Name | Confirmed | Default | Effect | doc_mentioned |
|---|---|---|---|---|
| `CLAUDE_STREAM_IDLE_TIMEOUT_MS` | ✅ | `90000` (90 s) | Client-side idle timer on the SSE stream. Expires → "API Error: Stream idle timeout". Reset on every chunk. Empirically measured: all timeouts 90.0–91.7 s (CaptFaraday, #49500). | No |
| `CLAUDE_ENABLE_STREAM_WATCHDOG` | ✅ | off | 30 s warning + 60 s abort (via AbortController) + non-streaming retry. Reset on every SSE frame (including `:ping`). **In code since v2.1.50, default disabled.** Kolkov #33949. | No |
| `CLAUDE_ENABLE_BYTE_WATCHDOG` | ⚠️ | off | Byte-level variant of the stream watchdog (post-v2.1.88). Presumably tracks real content bytes instead of SSE frames → fixes the "ping resets watchdog" problem of `ENABLE_STREAM_WATCHDOG`. Exact thresholds unknown. | No |
| `CLAUDE_SLOW_FIRST_BYTE_MS` | ⚠️ | unknown | TTFB-specific threshold. Exceeding it triggers logging/telemetry — **no abort**, purely diagnostic. Directly useful for Monitor_CC TTFB diagnosis. | No |
| `API_TIMEOUT_MS` | ✅ | unknown | Top-level HTTP request timeout over the entire API call. **Separate variable** from `CLAUDE_STREAM_IDLE_TIMEOUT_MS` — controls a different timeout. Default unknown. | No |
| `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` | ⚠️ | unknown | Stall timeout for async background agents (Task with `run_in_background: true`). Complements `CLAUDE_STREAM_IDLE_TIMEOUT_MS` for the agent context. | No |
| `CLAUDE_CODE_RETRY_WATCHDOG` | ⚠️ | unknown | Controls retry-watchdog behavior. Exact mechanism unknown — presumably a retry-count cap or retry-backoff override for dead-connection recovery. | No |
| `CLAUDE_CODE_MAX_RETRIES` | ✅ | unknown | Maximum number of API request retries before a hard error. | No |
| `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` | ✅ | not set (fallback active) | Disables the non-streaming retry path that `CLAUDE_ENABLE_STREAM_WATCHDOG` uses after an abort. Useful when an abort without retry is desired. | No |
| `CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS` | ✅ | not set | Prevents fast-mode cooldown from being triggered by network errors. Keeps fast mode active despite transient errors. | No |
| `CLAUDE_CODE_STALL_TIMEOUT_MS_FOR_TESTING` | ✅ | not set | Stall-timeout override for tests — **not intended for production**, no meaningful user value. | No |
| `CLAUDE_CODE_SLOW_OPERATION_THRESHOLD_MS` | ✅ | unknown | Threshold for slow-operation telemetry logging. No abort, purely diagnostic. | No |
| `CLAUDE_CODE_REMOTE_SEND_KEEPALIVES` | ✅ | unknown | Controls whether the client sends keepalives to remote sessions. Relevant for remote/bridge mode where the client can be dormant. | No |

---

## 3. Env-Vars — Model / Routing / Capacity

| Name | Confirmed | Default | Effect | doc_mentioned |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | ✅ | — | Model override (highest priority after CLI `--model`). | Yes |
| `CLAUDE_CODE_SUBAGENT_MODEL` | ✅ | — | Model for subagents — separable from the main-loop model. | No |
| `ANTHROPIC_SMALL_FAST_MODEL` | ✅ | `claude-haiku-4-5` | Small/fast model for compaction, subagent tasks, background work. Default Haiku. Misconfiguration here is a known cause of stalls (#26224). | Yes |
| `FALLBACK_FOR_ALL_PRIMARY_MODELS` | ✅ | not set | Enables fallback for ALL primary models on overload — not only for fast-mode Opus. Complements the `--fallback-model` CLI flag. | No |
| `CLAUDE_CODE_DISABLE_FAST_MODE` | ✅ | not set | Disables fast mode (priority serving for Opus 4.6, 6x price). | No |
| `CLAUDE_CODE_SKIP_FAST_MODE_ORG_CHECK` | ✅ | not set | Skips the org-eligibility check for fast mode. | No |
| `CLAUDE_CODE_RATE_LIMIT_TIER` | ✅ | — | Override of the rate-limit tier. | No |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | ✅ | model-dependent | Max-context-token override. | No |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | ✅ | 8192 (escalates to 64k) | Max-output-token override. Default 8k, escalates to 64k under `max_output_tokens_recovery`. | No |
| `CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` | ✅ | unknown | Max concurrent tool calls — parallelism of streaming tool execution. | No |
| `CLAUDE_CODE_EFFORT_LEVEL` | ✅ | `unset` / `auto` | Effort-level override. `"unset"` or `"auto"` disables effort control entirely. | No |
| `CLAUDE_EFFORT` | ✅ | — | Alternative effort-override var (shorter form). | No |
| `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING` | ✅ | not set | Disables adaptive thinking (dynamic thinking-budget adjustment). | No |
| `CLAUDE_CODE_DISABLE_THINKING` | ✅ | not set | Disables extended thinking entirely. | No |
| `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` | ✅ | unknown | Percentage of the context window at which auto-compact triggers. | No |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | ✅ | unknown | Context-window size used for the auto-compact calculation. | No |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | ✅ | `claude-haiku-4-5` | Custom Haiku-model override. Missing/wrong → stalls (known workaround in #26224). | No |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | ✅ | — | Custom Sonnet-model override. | No |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | ✅ | — | Custom Opus-model override. | No |
| `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING` | ✅ | not set | Enables fine-grained tool streaming (token-by-token instead of block-level). | No |

---

## 4. Env-Vars — Auth / API Connectivity

| Name | Confirmed | Default | Effect | doc_mentioned |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | — | API key for direct API access. | Yes |
| `CLAUDE_API_KEY` | ✅ | — | Alternative API-key var (legacy). | Yes |
| `ANTHROPIC_BASE_URL` | ✅ | `https://api.anthropic.com` | Base-URL override for API proxy or custom deployment. | Yes |
| `CLAUDE_CODE_API_BASE_URL` | ✅ | — | CC-specific base-URL override (overrides `ANTHROPIC_BASE_URL`). | No |
| `ANTHROPIC_LOG` | ✅ | — | Request-logging level (`debug`, `info`, etc.). | Yes |
| `CLAUDE_CODE_EXTRA_BODY` | ✅ | — | Additional JSON fields in the API request body. Passed directly to the `messages` API. | No |
| `ANTHROPIC_BETAS` | ✅ | — | Beta header (comma-separated). | Yes |
| `ANTHROPIC_CUSTOM_HEADERS` | ✅ | — | Custom HTTP headers for all API requests. | No |
| `CLAUDE_CODE_HTTP_PROXY` / `CLAUDE_CODE_HTTPS_PROXY` | ✅ | — | HTTP/HTTPS proxy for all API connections. | No |
| `CLAUDE_CODE_PROXY_URL` | ✅ | — | Proxy-URL override (CC-specific). | No |
| `ANTHROPIC_UNIX_SOCKET` | ✅ | — | Unix socket instead of TCP for the API connection. Relevant for loopback proxy setups (like Monitor_CC). | No |
| `CLAUDE_CODE_CERT_STORE` / `CLAUDE_CODE_CLIENT_CERT` / `CLAUDE_CODE_CLIENT_KEY` | ✅ | — | mTLS client certificates for corporate-proxy setups. | No |
| `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` | ✅ | unknown | TTL for cached API-key-helper results. | No |

---

## 5. Env-Vars — Tool Execution / Session

| Name | Confirmed | Default | Effect | doc_mentioned |
|---|---|---|---|---|
| `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` | ✅ | unknown | Max-token cap for file-read tool output. Exceeding it → truncation. | No |
| `CLAUDE_CODE_GLOB_TIMEOUT_SECONDS` | ✅ | unknown | Timeout for glob operations. | No |
| `CLAUDE_CODE_PWSH_PARSE_TIMEOUT_MS` | ✅ | unknown | PowerShell parse timeout. | No |
| `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS` | ✅ | unknown | Timeout for session-end hooks. | No |
| `CLAUDE_CODE_BASH_MAINTAIN_PROJECT_WORKING_DIR` | ✅ | not set | Keeps the working directory consistent across Bash tool calls. | No |
| `USE_API_CONTEXT_MANAGEMENT` | ✅ | not set | Uses API-side context-management features. | No |
| `CLAUDE_CODE_ENABLE_TASKS` | ✅ | not set | Enables the task system. | No |
| `CLAUDE_CODE_IDLE_THRESHOLD_MINUTES` | ✅ | unknown | Idle threshold (minutes) for session idle detection. | No |
| `CLAUDE_CODE_IDLE_TOKEN_THRESHOLD` | ✅ | unknown | Token-count threshold for idle detection (complements `IDLE_THRESHOLD_MINUTES`). | No |

---

## 6. Env-Vars — Telemetry / Debug / Dev

| Name | Confirmed | Default | Effect | doc_mentioned |
|---|---|---|---|---|
| `CLAUDE_CODE_ENABLE_TELEMETRY` | ✅ | on | Telemetry on/off. Includes `tengu_streaming_stall` events that Anthropic receives automatically. | No |
| `CLAUDE_DEBUG` | ✅ | off | Debug mode — verbose logging. | No |
| `CLAUDE_CODE_DEBUG_LOG_LEVEL` | ✅ | — | Debug-log-level override. | No |
| `CLAUDE_CODE_DEBUG_LOGS_DIR` | ✅ | — | Directory for debug logs. | No |
| `CLAUDE_CODE_FRAME_TIMING_LOG` | ✅ | not set | Frame-timing logging for performance profiling. | No |
| `CLAUDE_CODE_COMMIT_LOG` | ✅ | not set | Enables the commit log. | No |
| `CLAUDE_CODE_PROFILE_QUERY` | ✅ | not set | Profiling for the query path. | No |
| `CLAUDE_CODE_PROFILE_STARTUP` | ✅ | not set | Profiling for startup. | No |
| `CLAUDE_CODE_PERFETTO_TRACE` | ✅ | — | Perfetto trace file path. | No |
| `CLAUDE_CODE_SLOW_OPERATION_THRESHOLD_MS` | ✅ | unknown | Slow-op telemetry threshold. | No |
| `CLAUBBIT` | ✅ | — | Feature-flag override (GrowthBook alternative for local tests). | No |

---

## 7. Dead-Code / Fragment Strings

Strings that appear in the binary as prefix templates or incomplete patterns — **not standalone env vars**:

| String | Type | Usage |
|---|---|---|
| `CLAUDE_CODE_` | Prefix fragment | Dynamically concatenated into a full var name |
| `CLAUDE_CODE_DISABLE_` | Prefix fragment | Template for `DISABLE_*` vars |
| `CLAUDE_HAIKU_` | Prefix fragment | e.g. `CLAUDE_HAIKU_` + model suffix for Haiku-specific overrides |
| `CLAUDE_OPUS_` | Prefix fragment | Analogous for Opus |
| `CLAUDE_SONNET_` | Prefix fragment | Analogous for Sonnet |
| `CLAUDE_PLUGIN_OPTION_` | Prefix fragment | `CLAUDE_PLUGIN_OPTION_` + plugin name for plugin options |
| `CLAUDE_BASE` | Unclear | Possibly a partial match of `CLAUDE_BASE_URL` or similar — no standalone use case identified |
| `CLAUBBIT` | Borderline | In the binary, in INSIGHTS.md, but no clear production use case |

---

## 8. Latency Subset — Highlight + Recommendations

*These vars have a direct effect on TTFB / stream stalls / retry. Concrete recommendations.*

### Recommended `~/.claude/settings.json` `env` block

```json
"env": {
  "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "300000",
  "CLAUDE_ENABLE_STREAM_WATCHDOG": "1",
  "CLAUDE_ENABLE_BYTE_WATCHDOG": "1",
  "CLAUDE_SLOW_FIRST_BYTE_MS": "8000"
}
```

### Rationale per var

| Var | Recommendation | Reasoning |
|---|---|---|
| `CLAUDE_STREAM_IDLE_TIMEOUT_MS` | `300000` (5 min) | Default 90 s is too aggressive for Opus 4.7 + extended thinking + large writes. 5 min → no spurious abort, but sessions that are truly dead still die within session length. Do **not** set 1,800,000 (CaptFaraday's fix) — on a real stall the error message then takes 30 min. |
| `CLAUDE_ENABLE_STREAM_WATCHDOG` | `1` | Enables 30 s warning + 60 s abort + retry. Catches real dead connections. Drawback: reset on `:ping` — server keepalives can dummy-reset the watchdog. Still better than off. |
| `CLAUDE_ENABLE_BYTE_WATCHDOG` | `1` | Newer variant (post-v2.1.88), presumably byte-level instead of frame-level → fixes the ping-reset flaw. Enable both until it's clear which is better. |
| `CLAUDE_SLOW_FIRST_BYTE_MS` | `8000` | Logs all TTFB events > 8 s. Purely diagnostic, no abort effect. Valuable for Monitor_CC TTFB diagnosis — then appears in logs/telemetry. |
| `API_TIMEOUT_MS` | as-is (do not set) | Unknown default — better not to change without knowing what it overrides. If stalls persist: determine the value from binary context (open question). |
| `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` | not set (leave) | Fallback is useful — when the watchdog detects a stall and aborts, the non-streaming retry should get a chance. |
| `CLAUDE_CODE_RETRY_WATCHDOG` | as-is | Mechanism unknown — do not set blindly. |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `claude-haiku-4-5` | Only relevant when `ANTHROPIC_BASE_URL` points at a custom provider. Missing there → known stall cause (#26224). |

### What does NOT fix stalls

- None of these vars fix server-side stalls — they only improve how the client handles them (earlier abort, faster recovery, better diagnostics).
- The real fix would be on Anthropic's side: enabling the watchdog by default (flipping a boolean in their codebase, #33949 prompt 1).
- The `--fallback-model sonnet` CLI flag is a runtime hedge for interactive use when Opus is the congested path.

---

## 9. Open Questions

| Question | Relevance | Next step |
|---|---|---|
| What is the default value of `API_TIMEOUT_MS`? | High — could explain why some users see 5-min stalls without a stream-idle error | Binary-context analysis: read the bytes around the string `API_TIMEOUT_MS` in the binary, look for numeric values |
| Exact mechanism of `CLAUDE_ENABLE_BYTE_WATCHDOG` — what threshold, what triggers as "byte activity"? | Medium — determines whether it actually fixes the ping-reset flaw | Wait for a v2.1.88+ source-map leak or further binary analysis (context bytes around the string) |
| What exactly does `CLAUDE_CODE_RETRY_WATCHDOG` do? | Medium — could be another retry-tuning lever | Binary-context analysis |
| Default of `CLAUDE_SLOW_FIRST_BYTE_MS` — what value already counts as "slow" per Anthropic? | Medium — sets baseline for TTFB diagnosis | Binary-context analysis or wait for a source leak |
| ~~`CLAUDE_MOCK_HEADERLESS_429`~~ — was in INSIGHTS.md (v2.1.88), but **not in the v2.1.121 binary**. Removed between v2.1.88 and v2.1.121. | Closed | Binary check performed: no match |
| Which vars were added vs. removed between v2.1.88 and v2.1.121? | Medium — full post-leak delta | `npm_version_diff_vars` wishlist tool would resolve this; manually: download v2.1.88 binary + diff |
