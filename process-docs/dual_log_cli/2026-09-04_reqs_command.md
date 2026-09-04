# New command: `duallog reqs` — REQ number + time per session, 2026-09-04

Continues this area's command-surface line, and pairs directly with the same day's `msgs --req`
work: that feature translates a KNOWN REQ number into a msg-index range, but an agent scanning for
"which REQ do I even want" first had to run `msgs <s>` and eyeball separators, or `sessions` and
guess. `reqs` is the missing bare index — a session's REQ numbers and times, nothing else,
across as many sessions as `search` already knows how to scope.

## Design: a fifth command, not a `msgs` flag

`reqs` prints across MULTIPLE sessions (like `sessions`/`search`), not within one already-resolved
session (like `msgs`/`expand`) — so it needed its own subcommand and its own scoping loop, not
another `msgs` flag. The scoping loop is `search`'s, copied almost verbatim: `filter_sessions`
(scope substring + date window) then a per-session `load_timeline` try/except, skip-on-unloadable,
counted into the same trailing `(N sessions skipped …)` note `search` already prints. The one new
filter, `--main`/`--worker`, is a plain rendered-context PREFIX check (`"opus/"` / `"worker/"`) —
deliberately NOT folded into `filter_sessions`' own substring-matching parameters, since it is a
different filter class (prefix, not substring; mutually exclusive; `reqs`-only) and adding an
unused parameter to a function three OTHER commands share would have been the wrong trade.

## Reusing `request_markers`, not `render_msgs`

The output shows exactly what `msgs`' own separators already show — same numbers (re-fires
collapsed, a restart handled identically), same clock format — because it reads the SAME
`timeline.request_markers(boundaries)` dict `render_msgs` builds internally, just walked directly
instead of interleaved with msg lines. No new numbering logic, no new boundary-walking code;
`render_reqs` only decides how to LAY OUT what `request_markers` already computed (sorted by msg
index, one line per entry) — verified against the corpus below, not merely assumed to match.

## What `reqs` does NOT reuse from `search`

`search` only lists a session when it actually MATCHED something — a session with zero hits is
silently absent. `reqs` has no matcher at all, so it lists every session that LOADS successfully,
even one with zero requests (its `session <stem>` header still prints, no `REQ` lines beneath) —
closer to `sessions`' "show everything in scope" than to `search`'s "show only positives". This
was a deliberate reading of "list per session", not an oversight: a `reqs` run that silently
dropped an empty session would look like a filtering bug to a caller who did not yet know that
session was empty.

## Verification

- New suite `dev/dual_log_cli/tests/test_reqs.py` (11 checks): a single session's REQ lines
  reproduce the milestone's own worked example (`api_requests_worker_25c51a2e_proxy-tn-wrap_...`,
  `REQ 1 20:16:02` / `REQ 2 20:16:40`) byte-for-byte, built via the real `request_boundaries` over
  a temp `_forwarded.jsonl` (matching this area's established fixture style); a re-fire that
  eventually completes is collapsed into ONE `REQ` line carrying the OWNER's timestamp, not the
  re-fire's — caught a wrong first draft of this exact test, where the fixture accidentally put the
  re-fire in a DIFFERENT group than the one it actually shares (a re-fire only merges with a LATER
  boundary sharing its OWN `start_index`, not with whatever opened index 0); multiple sessions stay
  in listing order, blank-line separated; a zero-request session still gets its header; the
  skipped-note trailer; the empty-results fallback; and `filter_by_family` on hand-built
  `{"context": ...}` dicts for `--main`/`--worker`/neither.
- Full re-run of all 10 suites in `dev/dual_log_cli/tests/`, all passing — confirming `sessions`,
  `search`, `msgs`, `expand` untouched by this addition (none of `discovery.py`'s existing
  functions, `render.py`'s existing functions, or `__main__.py`'s existing `_run_*` functions were
  edited — only new functions added alongside them).
- Real invocation on the corpus: `reqs monitor_cc --since 2026-09-03 --until 2026-09-03 --main`
  lists `api_requests_opus_monitor_cc_1788464543`'s REQ 1 at `19:42:31` — the exact same number and
  clock `msgs monitor_cc_1788464543`'s own `── REQ 1  19:42:31 ──` separator already showed earlier
  the same day; `--worker` correctly excludes it and includes worker sessions instead (one, real,
  `proxy-tn-wrap`, closely matching the milestone's own illustrative example, coincidentally);
  `--main --worker` together is rejected by argparse's own mutually-exclusive-group error (exit 2,
  no code of this feature's own needed to enforce it); a nonexistent scope prints `no sessions
  found`, exit 0; `sessions`/`search`/`msgs`/`expand` re-invoked and confirmed unaffected.

## Relevant Symbols / Paths

- `render_reqs`, `_REQ_NUMBER_WIDTH` (`src/dual_log_cli/render.py`)
- `filter_by_family` (`src/dual_log_cli/discovery.py`)
- `_run_reqs` (`src/dual_log_cli/__main__.py`)
- Ground truth for the byte-identity check against `msgs`:
  `src/logs/dual_log/api_requests_opus_monitor_cc_1788464543_forwarded.jsonl`
- Area: this same area's `2026-09-04_msgs_req_range.md` — the sibling feature `reqs` is meant to
  feed into (find the REQ number here, resolve its msg range there)
