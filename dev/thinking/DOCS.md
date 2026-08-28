# dev/thinking/

## Role

Verification tooling for the proxy pane's thinking-related display features: the per-request
"brain marker" (🧠 badge on the REQ header) and the thinking-block drill-down + wrapping inside
an expanded REQ. Touch this when changing `has_thinking_delta` computation
(`src/proxy_display/forwarded_parser.py`), the badge rendering
(`src/proxy_display/render_turn.py::_build_req_header_line`), or the thinking-block toggle/wrap
(`src/proxy_display/render_messages.py::_render_block_spans`/`_wrap_thinking_text`,
`src/utils.py::wrap_visible`).

## Scripts

### render_brain_badge.py (136 LOC)

**Purpose:** Renders a real `_forwarded` dual-log through the actual parse + render path
(`forwarded_parser._parse_forwarded_log` → `render_turn._build_req_header_line`, no
reimplementation of the badge logic) and reports, per request, whether `🧠` appears in the
rendered header. Also computes an independent CUMULATIVE cross-check (any `thinking` block
anywhere in the full accumulated message list) to demonstrate the delta variant is the narrower,
informative one — the milestone's stated rationale for delta-over-cumulative semantics.

**Usage:**
```bash
# defaults to src/logs/dual_log/api_requests_opus_monitor_cc_1787931850_forwarded.jsonl
python3 dev/thinking/render_brain_badge.py
python3 dev/thinking/render_brain_badge.py path/to/other_forwarded.jsonl
```

**Measured (2026-08-28, live runtime log — the file keeps growing across sessions, so absolute
counts drift; re-run for current numbers):** 48 opus / 13 haiku requests; 26/48 opus carry 🧠
under delta semantics, 0/13 haiku; cumulative cross-check gives 47/48 opus (only the very first
opus request, before any assistant turn exists, is cumulative-negative) — confirming delta is
meaningfully narrower than cumulative, same shape the milestone spec describes.

**Reads:** a `_forwarded` dual-log JSONL file (path arg or the default above; the log itself is
runtime-only, gitignored under `src/logs/`, not vendored in the repo).
**Writes:** `dev/thinking/md/render_brain_badge_<timestamp>.md` (per-request table + aggregate counts).
**Called by:** nobody — standalone verification script, run manually.
**Calls out:** `src.proxy_display.forwarded_parser`, `src.proxy_display.render_turn`,
`src.proxy_display.format`, `src.utils` (all via `importlib.import_module`, per dev/ import convention).

---

### render_thinking_expander.py (256 LOC)

**Purpose:** Verifies the thinking-block drill-down + wrapping against a real `_forwarded` log,
through the REAL render path (`render_turn._render_req_expanded`, not a reimplementation).
Three checks, matching the milestone's own verification spec: (1) collapsed — a thinking block
occupies exactly one line and leaks no thinking text, proven by diffing a from-scratch collapsed
render against a single-key-expanded render (prefix/suffix around the header line must be byte
identical — the ONLY difference is the inserted content block); (2) expanded — the full text is
present (whitespace-normalized match against `blk['full_text']`, so re-wrapped whitespace can't
hide a false pass) and no content line exceeds `pane_width` cells, checked at 180 (the milestone's
own clipping example) and 60 (narrow stress width); (3) byte-identical — a non-thinking block's
`_render_block_spans` output is identical before and after this milestone's `render_messages.py`
edit, proven by loading the PRE-CHANGE file straight from git (`BEFORE_COMMIT_SHA`, pinned to the
commit preceding the edit) into an isolated `old_snapshot.src...` package under `/tmp` — a real,
separately-rooted package tree so the old file's relative imports (`from ..constants import
...`) resolve without colliding with the live `src` package already in `sys.modules` — and
calling its old-signature `_render_block_spans` against the same real block data the new one
renders, for one real block of each non-thinking type in the log (text, tool_use, tool_result,
image). Also determines which `(entry_idx, msg_idx, bidx)` thinking blocks are actually owned by
a given entry's own rendered delta empirically (`think_key` present in that entry's own
from-scratch render), not inferred — a message re-appears in every LATER entry's accumulated
`messages` too, but only the entry whose own delta introduced it renders it (same delta-vs-
cumulative distinction as `render_brain_badge.py`'s brain marker).

**Usage:**
```bash
# defaults to src/logs/dual_log/api_requests_opus_monitor_cc_1787931850_forwarded.jsonl
python3 dev/thinking/render_thinking_expander.py
python3 dev/thinking/render_thinking_expander.py path/to/other_forwarded.jsonl
```

**Measured (2026-08-28):** 26 owning thinking blocks found in the log — collapsed 26/26 ok,
expanded 52/52 ok (26 blocks × 2 pane_widths), byte-identical 4/4 non-thinking types ok. Exits 1
if any check fails.

**KNOWN LIMITATION the probe does NOT cover (unmeasured, not ruled out):** `_render_span_content`
ignores `full_text` entirely when `i_blk` is new-format span data — a thinking block carrying its
own strip/inject spans would render them unwrapped, bypassing this milestone's wrap. This script's
`check_non_thinking_byte_identical` never exercises that coordinate for a thinking block (it only
runs the byte-identical check on non-thinking types), and no thinking block in the sampled log
carried spans either — the absence is a property of this one log, not a proof the coordinate is
unreachable. See `process-docs/thinking/` for the full note.

**Reads:** a `_forwarded` dual-log JSONL file (path arg or the default above), plus `git show` of
`BEFORE_COMMIT_SHA` for the byte-identical check (requires the commit to exist in the local repo).
**Writes:** `dev/thinking/md/render_thinking_expander_<timestamp>.md` (three result tables +
aggregate counts); a throwaway package tree under a `tempfile.mkdtemp` `/tmp` dir (not cleaned up
— harmless, same as any other `/tmp` scratch artifact).
**Called by:** nobody — standalone verification script, run manually.
**Calls out:** `src.proxy_display.forwarded_parser`, `src.proxy_display.render_turn`,
`src.proxy_display.render_messages`, `src.proxy_display.format`, `src.utils`, `git` (subprocess,
`show` only) — all Python imports via `importlib.import_module`, per dev/ import convention.
