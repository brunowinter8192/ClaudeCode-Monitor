# 2026-07-31 — Ninth unguarded pane loop: news_pane/log_pane.py

## Problem

The initial pane-loop-resilience sweep enumerated 7 unguarded loops by symptom: the user reported
window `1:proxy` vanishing from the tmux status bar, and tmux only destroys a WINDOW when its
LAST pane's process exits. The enumeration missed `run_news_log_loop` in
`src/news_pane/log_pane.py` (window 5, pane 5.1) because window 5 has TWO panes (5.0 control +
5.1 log-tail) — that loop dying silently leaves pane 5.1 blank while window 5 itself survives (its
sibling pane 5.0 keeps the window alive), so it never produces the "window vanishes" symptom that
drove the original enumeration. Same silent-death class applies regardless: the loop's
`while True:` body had a `try/except OSError` around only `os.get_terminal_size()` —
`find_log_file()`, `find_current_run_lines()`, `filter_events()`, `_render_log_pane()`, and the
`print()` calls were all unguarded.

## Fix

Same shared sink (`log_pane_error('news_log')`), same nesting pattern (new outer
`except Exception:` wraps the whole body, the pre-existing inner `try/except OSError` around
`os.get_terminal_size()` preserved unchanged inside it) as the other 8 loops. Two real
differences from every other loop, both left as-is per this loop's own shape rather than forced
into the common pattern: this loop has no keyboard/mouse handling at all (tmux native scroll is
used instead, so there is nothing to no-op or count), and no `finally:` block (nothing needs
`disable_mouse()`/`restore_terminal()` cleanup since neither was ever enabled) — the guard was
added without inventing either.

## Verification

The existing probe's injection strategy (patch `read_keypress` to raise once) doesn't apply here
— this loop never calls `read_keypress`. Injected instead via `find_log_file()`, with `time.sleep`
(not `wait_for_input`) as the tick/stop counter — a second, narrower harness function
(`_run_poll_only_loop_and_capture`) added alongside the existing one rather than generalizing it,
since this is the only loop of the 9 with this exact no-keyboard/no-finally shape.
`dev/pane_error_log/p1_pane_loop_survives_exception_probe.py`: 52/52 checks passed (48 from the
original 8 loops + 4 new for `news_log`: terminated via the `BaseException` stand-in rather than
an unhandled crash, survived past the injected-crash iteration, logged with the `[news_log]`
identifier and a full traceback). Same integration-level boundary as the original 8: real
`run_news_log_loop()` invoked directly, not a live tmux pane kill.
