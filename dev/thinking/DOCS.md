# dev/thinking/

## Role

Verification tooling for the proxy pane's per-request "brain marker" (🧠 badge on the REQ header
when a request's message delta carries a thinking block). Touch this when changing
`has_thinking_delta` computation (`src/proxy_display/forwarded_parser.py`) or the badge rendering
(`src/proxy_display/render_turn.py::_build_req_header_line`).

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
