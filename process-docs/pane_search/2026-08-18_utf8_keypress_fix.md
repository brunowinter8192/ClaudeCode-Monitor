# Proxy pane search — follow-up: UTF-8 multi-byte keypress bug

**Date:** 2026-08-18 (continues the `pane_search` area; follow-up to the M2 search-bar entry)

## Symptom (user-reported, live)

Typing an em-dash into the proxy pane's search bar rendered three replacement characters
(`���`) instead of the em-dash.

## Root cause — confirmed, not assumed

`input.click_handler.read_keypress()` performed `os.read(_stdin_fd, 1)` — exactly one byte —
then decoded that single byte as UTF-8 with `errors='replace'`. An em-dash (U+2014) encodes to
3 UTF-8 bytes (`E2 80 94`); each byte arrived via a SEPARATE `read_keypress()` call (the pane's
drain loop calls it repeatedly), and each byte alone is not valid standalone UTF-8 → each
decoded to U+FFFD independently, producing three `'�'` characters appended one at a time into
the search query.

## Caller survey (all 7 read before deciding fix placement)

`read_keypress` is called from `core/monitor.py`, `gpu_pane/pane.py`, `news_pane/pane.py`,
`panes/token_pane.py`, `panes/warnings_pane.py`, `workers/worker_pane.py`,
`proxy_display/pane.py`, `proxy_display/worker_proxy_pane.py`. Of these, only two panes
accumulate free-text input from `char` (main pane's `_handle_main_search_input` in
`core/monitor.py`/`core/monitor_display.py`, and the proxy pane's `_handle_proxy_search_input`
in `proxy_display/pane.py`) — the rest do single-hotkey comparisons (`char.isdigit()`, `char in
('r','R')`, digit-key dispatch). Because a Python string for one Unicode codepoint is always
`len == 1` regardless of source UTF-8 byte-width, fixing decoding at the source changes NOTHING
observable for the single-hotkey panes (today a `'�'` matches none of their branches; after the
fix a correctly-decoded non-ASCII character also matches none of their branches — same no-op
outcome). `read_mouse_event`'s own byte-wise reads (parsing `\033[<btn;col;rowM`) are ASCII-only
by protocol and were confirmed untouched — no multi-byte case can occur inside a mouse sequence.

## Fix

`read_keypress()`: read the lead byte first (unchanged non-blocking `select.select(..., 0)` fast
path for "nothing pending" → `None`), classify it via a new `_utf8_continuation_count(lead_byte)`
helper using the UTF-8 lead-byte bit pattern (`0xxxxxxx`=0 continuation bytes, `110xxxxx`=1,
`1110xxxx`=2, `11110xxx`=3), then read that many more bytes — each gated by
`select.select(..., 0.005)`, the SAME timeout value `read_mouse_event` already uses for its own
byte-wise ESC-sequence continuation reads (reused for consistency with an established pattern in
the same file, not invented fresh) — and decode the full accumulated byte sequence together.
Plain ASCII (the overwhelming majority of keypresses) takes 0 extra reads — byte-for-byte
identical code path to before the fix, zero added latency.

Also dropped the `try/except Exception: pass` that wrapped the read — a project hook flagged the
blanket-swallow pattern on re-edit. Every one of the 7 pane loops already wraps its drain loop in
its own `try/except Exception: log_pane_error(...)`, so letting a read error propagate up now
surfaces it in the pane's own error log instead of hiding it inside `read_keypress` — same
graceful-recovery outcome (pane keeps running), now visible instead of silent.

## Verification

- **Integration-level, real I/O:** fed the literal UTF-8 byte sequences for an em-dash (3 bytes),
  ä/ö/ü (2 bytes each), and a 4-byte emoji through a REAL `os.pipe()` file descriptor
  (`click_handler._stdin_fd` monkeypatched to the pipe's read end) into the actual
  `read_keypress()` function — not a mock, real `os.read`/`select.select` calls. All six decoded
  to exactly the correct single character; a back-to-back em-dash+`'a'` case confirmed
  continuation-byte reads never over-consume into the next keypress.
  `dev/pane_search/p2_search_feature_regression_test.py` (`test_utf8_multibyte_keypress`,
  `test_utf8_search_query_accumulation`), folded into the existing M2 regression suite rather
  than a new file (same regression area).
- **Main-pane claim verified, not assumed:** ad-hoc script (not committed — one-shot verification,
  no standing regression value beyond confirming the shared-function fix) fed the same byte
  sequences through `core.monitor._handle_main_search_input` and confirmed
  `core.monitor_display._search_query` accumulated `'foo —ä😀'` with no `'�'` present — the main
  pane's search bar is healed by the same fix, as claimed.
- **Regression check:** `dev/click_ui/p3_button_click_probe.py` (32/32) and
  `dev/proxy_dual_log/A_render_refactor_proof.py` (14/14 byte-identical) both re-run clean — the
  `click_handler.py` change is isolated to keypress decoding and doesn't touch rendering or mouse
  handling.
- **Not verified as of this entry:** live tmux typing of an actual em-dash/emoji via a real
  keyboard — the byte-sequence-through-a-real-pipe tests exercise the exact same code path a
  terminal would drive, but a live keystroke is the final confirmation, left to the user.

## Scope note for the next milestone

Left `_handle_proxy_mouse`'s `row == 1` branch as a plain "any click focuses" handler — no
motion/drag tracking added or removed. The next planned milestone (drag-to-select on the search
bar: press-anchors, motion-extends, release-copies) was flagged in advance specifically so this
session's work wouldn't refactor row-1 mouse handling in a way that would fight it; no such
refactor was made.
