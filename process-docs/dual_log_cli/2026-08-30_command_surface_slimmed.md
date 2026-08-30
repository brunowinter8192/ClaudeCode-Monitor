# 2026-08-30 — duallog command surface slimmed to sessions / expand / search

## What changed

Two user-facing removals, no behavior change to what survives:

1. The `timeline` command was deleted. It rendered a whole session as one classifier line per msg
   plus one line per block, with `── REQ n ──` boundary markers and a header block.
2. `expand` lost its classifier-rows overview mode and is now always the full-content dump that
   `--full` used to select. `--full` is gone, `--before`/`--after` became optional with default 0,
   and the 30-row hard floor died with the overview.

`sessions` and `search` were untouched.

## Why

The two removed views were both *listings*: they told the reader which msgs exist and roughly how
big they are. In practice an agent reaching for the CLI already knows what it is looking for and
gets there through `search` (which reports msg indices) — the listing step in between produced a
lot of tokens for a navigation aid that `search` output already provides. The overview's 30-row
floor made that worse: it was deliberately un-narrowable, so the cheapest possible overview call
still printed ~61 rows plus block sub-rows.

The surviving surface is therefore: `sessions` to find the session, `search` to find the msg index,
`expand` to read it.

## What stayed, and why the removal did not cascade further

The internal timeline is the shared machinery of the whole package and stayed intact:
`load_timeline`, `build_turns`, `iter_block_texts`, `request_boundaries`, `build_turn_times`,
`full_turn`. `search` reconstructs a session through exactly this path — that reconstruction is
what makes a hit deduplicated (the searched payload is the single last request, which already
embeds the whole conversation), so dropping any of it would have changed `search` semantics.

Removed as dead code after the two commands went:

| Symbol | Module | Was reachable only from |
|---|---|---|
| `render_timeline`, `_timeline_header`, `_boundary_line` | render.py | `timeline` command |
| `fmt_bytes` | render.py | `_timeline_header` |
| `boundaries_by_index` | timeline.py | `render_timeline` |
| `render_expand_overview` | render.py | expand overview mode |
| `_OVERVIEW_FLOOR`, `_run_timeline`, `_run_expand_full` | \_\_main\_\_.py | the removed modes |

Two things were deliberately NOT removed, because they are data fields inside shared structures
rather than unreachable code, and stripping them would have rippled into functions that all three
commands still use:

- `build_turns` keeps filling `preview` and `sig_chars` per block. Only `render_timeline` read
  them; removing them would have pulled `_block_preview`/`_preview` out with them and changed the
  turn-row contract that `expand` also consumes.
- `load_timeline` keeps returning `entry`, `family`, `line_bytes`, `haiku_lines_skipped` and
  `boundaries`. Only the removed timeline header read the first four; `boundaries` is still the
  input `build_turn_times` consumes inside `load_timeline` itself.

## Consequences worth knowing

The restart WARNING is gone from the output. A message-count regression (CC restarted inside one
log id) used to be announced in words by the timeline header. `build_turn_times` still refuses to
trust the pre-restart chain, so the regression is now visible only as `?` in `expand`'s time
column — the conservative behavior is unchanged, only its announcement disappeared.

Request boundaries no longer reach the reader as markers, only as the HH:MM:SS column derived from
them.

## Verification (2026-08-30)

Outputs were captured before the change and diffed against the post-change run on session
`api_requests_opus_gh_cli_1787995963` (1417 msgs):

- `sessions` (12 sessions) — byte-identical.
- `search worker <session>` (390 lines) — byte-identical.
- `expand <s> 40` after vs. `expand <s> 40 --full --before 0 --after 0` before — byte-identical
  (11 lines).
- `expand <s> 40 --before 2 --after 1 --only user` after vs. the same call with `--full` before —
  byte-identical (93 lines).
- `expand <s> 40 --before 3 --after 3` vs. its `--full` predecessor (219 lines) — byte-identical.

Error paths: `timeline <s>` exits 2 with `invalid choice: 'timeline'`; `--full` exits 2 with
`unrecognized arguments: --full`; `--before=-1` exits 2 with the bounds message; an out-of-range
msg and an unknown `--only` token keep their exit-2 messages. Piping a 81-msg dump through `head`
produced no `Exception ignored while flushing sys.stdout`, so the broken-pipe guard still holds.

An AST pass over the package reported zero unused imports and zero module-local unreferenced
functions afterwards. `reader.read_json_line` has no caller, but it had none before this change
either — pre-existing, left alone.
