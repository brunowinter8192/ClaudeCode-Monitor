# dev/bg_wakeup_id_line/

## Role

Measurement + verification scripts for the CC background-launch-ack family: what the raw ack
text looks like across real wordings (`p1_`), the tmux-Escape mechanism the proxy fires off that
detection (`p2_`, `src/proxy/bg_escape.py`), and the marker CC itself records in the conversation
when that Escape lands mid-tool-call — `"[Request interrupted by user]"` or `"...for tool use]"`,
both trailing-`\n`-terminated, stripped by `src/proxy/strip_interrupt_marker.py` (`p3_`). `md/`
holds every script's report.

## Modules

### p1_scan_launch_ack_wordings.py (291 LOC)

**Purpose:** Inventories distinct CC background-launch-ack wordings in the recorded corpus
(`src/logs/dual_log/*_original.jsonl`), dedups cumulative dual-log duplication, evaluates the
3 real recognition mechanisms (`src/proxy/strip_bg_launch_ack.py`) against each wording.
**Reads:** `src/logs/dual_log/*_original.jsonl`.
**Writes:** `md/launch_ack_wordings_<date>.md`.
**Called by:** run manually — measurement only, not a regression guard.
**Calls out:** `src/proxy/strip_bg_launch_ack.py` (imports the real markers/regexes).

---

### p2_bg_escape_probe.py (339 LOC)

**Purpose:** Verifies `src/proxy/bg_escape.py` — the tmux-Escape-on-launch-ack mechanism.
8 test groups: dedup across repeated acks (real 142/169 shape), two distinct task ids → two
Escapes, both CC wordings trigger, a `main` (non-worker) context never triggers, tmux session
name derivation from `PROXY_LOG_ID` + `PROXY_PROJECT_PATH` (including a hyphenated worker name),
**a fire writes one JSONL trace line to `bg_escape_events.jsonl` under a `MONITOR_CC_ROOT`-scoped
temp dir (task id, tmux session, send result), a main-context skip logs `reason='main_context'`,
and a request with no ack chunk at all never creates the log file (2026-07-30)**, a real tmux
round trip (throwaway session, real `send-keys`, `capture-pane` proof), and failure isolation
(dead/missing tmux session, missing `tmux` binary — both at the unit level and through a real
`ProxyAddon.request()` call with the binary simulated absent).
**Reads:** Nothing persistent — builds all fixtures in-process; spawns/kills one throwaway tmux
session for the round-trip test; the log-line test scopes `MONITOR_CC_ROOT` to a `tempfile.TemporaryDirectory()`, never the real `src/logs/`.
**Writes:** `md/p2_bg_escape_probe_<timestamp>.md`.
**Called by:** run manually — regression guard for `bg_escape.py`; re-run after any change to
`strip_bg_launch_ack.py`'s detection or `addon.py`'s worker-context derivation.
**Calls out:** `src/proxy/bg_escape.py`, `src/proxy/addon.py` (`ProxyAddon`, `_derive_worker_context`), `tmux` binary (Test 6 only).

---

### p3_strip_interrupt_marker_probe.py (243 LOC)

**Purpose:** Verifies `src/proxy/strip_interrupt_marker.py` and its full wiring through
`message_passes.py` / `rules.py` / `strip_vocab.py` / `strip_inject_delta.py`. 7 test groups: the
real measured 3-block shape (`tool_result` / marker(+trailing `\n`) / injected wake-up) with
byte-identical neighbors after strip, all 4 content shapes, the 2nd real wording ("for tool use"),
the false-positive class (marker embedded inside longer text left untouched, incl. a real
corpus-derived 180-char quote), message-pass role-gating + mod naming,
`strip_vocab`/`_MSG_CODE_TO_FN` attribution (`IM` code, both wordings), and a full-pipeline check:
real `apply_modification_rules` → real `_build_stripped_injected_deltas`, asserting
`fn_map['msg.0.1'] == '_apply_interrupt_marker_strip'` (not `'unknown'`).
**Reads:** Nothing persistent — builds all fixtures in-process. The 2026-07-30 header's
"1791 occurrences" figure was an uncorrected per-request-log count and never reproduced; the
2026-07-31 re-measurement (last/fullest line per `src/logs/dual_log/*_original.jsonl` session
file) found 11 real occurrences across 5 session files, all trailing-`\n`-terminated, in 2
wordings — reproduced here as synthetic fixtures, not re-scanned (no real dual-log corpus in this
worktree).
**Writes:** `md/p3_strip_interrupt_marker_probe_<timestamp>.md`.
**Called by:** run manually — regression guard for `strip_interrupt_marker.py`; re-run after any
change to that module or its wiring.
**Calls out:** `src/proxy/strip_interrupt_marker.py`, `src/proxy/message_passes.py`
(`_apply_interrupt_marker_strip`), `src/proxy/rules.py` (`apply_modification_rules`),
`src/proxy/strip_vocab.py` (`attribute_chunk`, `RULES`), `src/proxy/strip_inject_delta.py`
(`_MSG_CODE_TO_FN`, `_build_stripped_injected_deltas`).

---

## Gotchas

**Test 6 (real tmux round trip) needs a real `tmux` binary on PATH and creates/destroys one
throwaway session (`__bg_escape_probe_<ts>__`).** Not sandboxed away from a real tmux server —
if no `tmux` is installed, this one check fails while the other 6 groups (pure-Python, no tmux
dependency) still run and report normally.

**The reader-pane pattern in Test 6 passes a SINGLE shell-string trailing argument to
`tmux new-session`** (`f'python3 {script}; sleep 5'`), not multiple trailing argv words —
multiple words make tmux `execvp` the command directly instead of routing through `$SHELL -c`,
which can tear the pane down before `send-keys` reaches it (see
`process-docs/escape_idle_worker/2026-07-30_tmux_escape_edge_trigger.md` for the original
diagnosis of this failure mode).
