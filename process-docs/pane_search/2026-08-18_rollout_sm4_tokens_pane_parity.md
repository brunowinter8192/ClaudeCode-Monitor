# Search-bar rollout — sub-milestone 4: tokens pane reaches parity

**Date:** 2026-08-18 (continues the `pane_search` area — sub-milestone 1 extracted the shared
mechanics into `src/search_bar.py` and retrofitted the proxy pane, sub-milestone 2 the main
pane, sub-milestone 3 the worker-proxy pane; this entry retrofits the tokens pane,
`src/panes/token_pane.py` + `src/format/token_format.py`)

## Scope

Tokens pane only. Structurally simpler than the proxy family: single expand level
(`cache_expand_states[(turn_idx, call_idx)]`, turns themselves never collapse — always fully
rendered), data ALWAYS fully loaded incrementally (no windowing, no reconstruction step —
`_tokens_search_on_commit` just calls the matcher directly over what's already in memory). Three
genuinely new pieces this milestone had to build: the sentinel bug fix (same class as the proxy
pane), the 2-row header shift, and the two-key match design.

## The sentinel bug — confirmed same class, fixed the same way

`constants.ZEBRA_BG_A == ''` (confirmed before writing any code) is the `chosen_bg` for every
non-hovered, non-`LIGHT_RED_BG` row and every expanded-detail line in `token_pane.py`'s own
hand-rolled zebra/hover row-background loop (`_build_tokens_output`) — identical trap to the one
`2026-08-18_highlight_flood_empty_bg_fix.md` fixed on the proxy pane. Fix: `token_format.py`
embeds search highlights with `search_bar._BG_RESTORE_SENTINEL` (not a hardcoded color) at
construction time; `_build_tokens_output` calls `search_bar.resolve_bg_restore(line, chosen_bg)`
unconditionally right after `chosen_bg` is chosen, per row — exact same fix shape, this time
realized in a pane's own inline loop rather than a separate `_apply_row_backgrounds` function
(the proxy pane's own architecture).

**Collateral fix caught during implementation, not review:** the pre-existing `LIGHT_RED_BG`
(cc_broken row) detection was `line.startswith(LIGHT_RED_BG)`. A container-marked search match
now PREPENDS `marker` before `_format_cache_call`'s own `LIGHT_RED_BG` prefix, so the literal
prefix check would silently stop detecting cc_broken rows whenever a match ALSO happened to be
cc_broken. Changed to `LIGHT_RED_BG in line` (substring) — provably equivalent to the old check
whenever no marker is present (a true prefix is always a true substring), so this is a
behavior-preserving generalization, not a new risk, for every non-search-match row. Caught by
writing the regression test (`test_light_red_bg_still_detected_when_call_is_also_a_match`)
before it would have shipped silently broken.

## 2-row header — approach

`format_cache_tracker`'s existing `_compute_cache_viewport` already reserved one row
UNCONDITIONALLY as a slot the optional `sticky_header` may or may not use (confirmed: when
`sticky_header is None`, that reserved row was already going unused — pre-existing, accepted
behavior, not something introduced this milestone). Left that internal `-1` completely
untouched. Instead, `_build_tokens_output` computes `content_height = pane_height -
_TOKENS_SEARCH_BAR_LINES` (new fixed constant, `=1`) and passes THAT as `format_cache_tracker`'s
own `pane_height` argument — the same "caller subtracts its own header rows before calling, the
renderer's internal reservation stays put" convention the proxy panes already established.
`phys_row` (a local counter in `token_pane.py`'s own render loop, not a separate shift-dict step
like the proxy panes' `line_map`/`copy_rows` post-hoc shift) now starts at `1 +
_TOKENS_SEARCH_BAR_LINES + (1 if sticky_header else 0)`.

**Known limitation, documented not fixed:** `_compute_cache_viewport`'s sticky-header
TRUNCATION path rebuilds the sticky header from ONLY a regex match on the "Turn N [...]"
substring, discarding a prepended search marker/sentinel when the matching turn line is long
enough to trigger truncation. Match data and jump-to-match remain correct; only that one visual
cue (the sticky header's own highlight color) can silently disappear in that narrow combination.
Left unfixed — proportionate to the actual impact (cosmetic-only, narrow triple-condition edge
case), would require restructuring the truncation logic. Documented in both `format/DOCS.md` and
`panes/DOCS.md`.

## Two-key match design — the actual decision

Two distinct match-key shapes, distinguished by tag (mirrors the codebase's existing `('req',
idx)`-style tagged-tuple convention already used throughout `proxy_display`):
- **`(turn_idx, call_idx)`** — a match found anywhere in that call's content. The matcher
  (`token_search.build_token_search_matches`) FORCE-renders the call's real header line
  (`token_format._format_cache_call`) plus real expanded detail lines
  (`_render_expanded_call_lines`) regardless of the call's actual `cache_expand_states` toggle —
  exactly "exactly what's rendered once expanded," the same principle the proxy pane's own
  matcher follows. **Collapsed → the whole call-header line gets an UNCONDITIONAL container
  mark** (`marker+line+sentinel`, not a literal-substring-only wrap — the matching text may be
  buried in unrendered detail the collapsed view never shows at all). **Expanded →
  additionally**, the specific matching detail line(s) get browser-find substring-highlighted;
  the header stays marked too (uniform, orientation-preserving — same decision the proxy pane
  made for its own REQ headers).
- **`('turn', turn_idx)`** — a match found in the turn's own prompt/timestamp line, the one
  thing with no expand state (always fully shown). Same unconditional whole-line container mark
  — there's no "collapsed vs expanded" distinction for a turn.

Critically: `('turn', idx)` keys are NEVER added to `line_keys`/`cache_line_map` — turn header
lines stay non-interactive for clicks exactly as before this milestone. A SEPARATE `nav_out`
out-param on `format_cache_tracker` (mirrors `proxy_display.format`'s `item_positions_out`/
`copy_rows_out` contract — cleared and rewritten in place, never returned) carries
`{key: absolute_line_idx, ..., 'total_lines': N}` purely for jump-to-match scroll math. This
split was verified deliberately against the SECOND real caller of `format_cache_tracker` —
`workers/worker_format.py`, which unpacks every non-None key as `(name, ck[0], ck[1])`, an
operation that would break the moment a `('turn', idx)` value ever appeared in `line_keys`. It
never does, by construction.

## `format_cache_tracker` signature growth — verified backward-compatible, zero return-arity change

Four new optional params (`search_match_set`, `search_current_key`, `search_query`, `nav_out`),
all defaulting to no-op values, appended at the end — the function still returns the SAME
5-tuple it always did. Verified against all 4 real callers found by grep before editing:
`token_pane.py` (5-value unpack), `workers/worker_format.py` (5-value unpack, positional args),
`dev/click_ui/p2_copy_click_probe.py`'s tokens test (5-value unpack), `dev/display/
A_format_cache_tracker_proof.py` (keyword `pane_height=`/`pane_width=` only, positional `turns`).
None needed updating.

## Byte-identity verification — the live-data-instability finding

Planned to mirror the M2 proxy milestone's before/after capture-then-verify pattern using `dev/
display/A_format_cache_tracker_proof.py`. Captured a baseline BEFORE touching the file (60
cases, 10 real session JSONLs under `~/.claude/projects/.../`). After implementing, `--mode
verify` reported 4-6 of 60 cases failing, inconsistently across repeated runs — never a stable
failure set. Root-caused rather than assumed a real regression: the harness's `_find_sessions()`
globs the TOP 10 MOST-RECENTLY-MODIFIED `.jsonl` files in that directory — the same directory
this very orchestrator's own Claude Code session (and potentially other concurrently active
sessions on the same machine) writes to live. Confirmed via `stat`: the specific failing
session's mtime was ~2.5 minutes newer than the moment the baseline was captured — the file
had genuinely grown in the interim, independent of any code change. Verified the hypothesis
directly: froze all 10 sessions' `_load_turns()` output to a pickle ONCE, then ran
`format_cache_tracker` against that FROZEN, held-constant snapshot with the pre-change code
(`git stash`) and the post-change code (`git stash pop`) in the same process — **0/60 mismatches**.
This is the reliable evidence; the live-file capture/verify artifacts were discarded (not
committed) since a checked-in baseline against this specific harness's data source would go
stale again almost immediately, for the identical reason, misleading the next person to touch
this file. The harness itself was left unmodified (out of this milestone's scope) — this
finding is a property of ITS data-source choice (live, most-recently-modified real sessions,
unlike the proxy pane's equivalent harness which reads fixed dual-log snapshot files), not a bug
introduced or fixed here.

## Decisions confirmed before implementing

- **Bar label `'search: '`** (lowercase) — proposed for overall visual consistency (3 of 4
  search-enabled panes now use lowercase; only the main pane is capitalized, a deliberate
  one-off decided in sub-milestone 2).
- **No overdraw needed.** The codebase's "Header + Body pane contract" (documented in
  `panes/DOCS.md`) requires an overdraw print for panes whose header could get pushed off-screen
  by wrapping body content — confirmed this doesn't apply here: `token_pane.py` (like
  `core/monitor.py`) truncates every line (`truncate_visible`) rather than wraps, so the
  precondition that triggers the symptom never occurs. The new row-1 search bar was added
  without adopting the overdraw pattern.

## Verification

- **78/78** new regression checks (`dev/pane_search/p6_tokens_pane_parity_test.py`) against real
  `src.panes.token_pane`/`src.format.token_format`/`src.panes.token_search` functions (via
  `importlib.import_module`, real calls — not mocked) with synthetic turns: the full mechanics
  suite (drag-select press→motion→release, plain-click zero-copy, selection-delete vs plain
  Backspace, kill-line, editing-never-clears-matches, `n`/`N` wrap, Esc clearing state while the
  bar stays visible, reverse-video render), the collapsed-container-mark vs expanded-substring
  distinction for call-level matches (with an explicit assertion that the matched text is
  invisible in the collapsed row's own rendered output, proving the matcher genuinely
  force-rendered it), turn-level matches (with an explicit `not in cache_line_map.values()`
  assertion), the exact `ZEBRA_BG_A==''` sentinel repro (explicit `\033[49m` present, zero
  leaked raw sentinel bytes), the `LIGHT_RED_BG` collateral-fix regression guard, jump-to-match
  moving `cache_scroll_offset` for an off-screen-by-default early match, and the session-change
  reset (real `_refresh_tokens_data` call, `core.monitor.get_main_session_files` +
  `proxy_display.parser.find_response_log_path`/`read_response_log` monkeypatched to a synthetic
  switch).
- **48/48** `p2`, **62/62** `p3`, **77/77** `p4`, **77/77** `p5` — all prior-milestone suites
  re-run clean (zero files this milestone touched outside `token_pane.py`, `token_format.py`,
  the new `token_search.py`, one dev/ test file, and DOCS.md).
- **35/35** `p1_worker_selection_click_probe`, **32/32** `p3_button_click_probe`, **37/37**
  `p2_copy_click_probe` (the last of these directly exercises the real, row-shifted
  `_build_tokens_output`/`_handle_tokens_mouse` for tokens-pane copy-click parity) — all re-run
  clean.
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py --mode verify` —
  confirms zero impact on `proxy_display/` (untouched this milestone).
- **0/60 mismatches** via the frozen-turns old-vs-new `format_cache_tracker` comparison
  (throwaway, not committed — see above) — the reliable byte-identity evidence for this
  milestone's signature growth.
- `dev/display/test_hover_map.py`: 40/40 of the tests that don't hit the pre-existing, unrelated
  `ImportError: _parse_log_file` (confirmed again this milestone via `git diff` — `parser.py`
  untouched — same finding first flagged in the sub-milestone 3 entry, still unaddressed,
  explicitly out of scope for every milestone in this rollout).
- Import-level sanity: `src.panes.token_pane`, `src.panes.token_search`,
  `src.format.token_format` all import cleanly post-migration (`ast.parse` + real
  `importlib.import_module`, no mocking).
- **Not verified as of this entry:** live tmux/terminal visual rendering of the tokens pane's
  bar and 2-row header, the `/` focus hotkey's live dispatch (a one-line branch inside
  `run_tokens_loop`'s while-loop, not unit-tested at the loop level — consistent with every
  prior milestone in this area), and real trackpad drag-select. Standard "user visual check"
  gate, same as every prior entry in this area.
