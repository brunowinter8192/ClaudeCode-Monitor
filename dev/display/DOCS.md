# Display Layer Tests

Scripts for testing and verifying the display layer (tmux layout, rules rendering, pane management).

## Working Directory

**CRITICAL:** All commands assume CWD = `Monitor_CC/` (project root)

## Scripts

### test_tmux_layout.sh (55 LOC)

Tests tmux pane layout for the monitor. Originally 3-pane, now 5-window / 10-pane (main+tokens | proxy+metadata | rules+hooks | workers+worker-proxy+worker-metadata | warnings).

**Purpose:** Verify pane indices after nested splits, confirm `-l` percentage behavior, validate `-b` flag for top/bottom placement.

**Usage:**
```bash
bash dev/display/test_tmux_layout.sh
```

**Output:** Pane index table showing dimensions and positions. Session auto-cleans after output.

**Source:** tmux man page (github.com/tmux/tmux `tmux.1` L3591-3648) — `-l size%` = percentage of target pane's available space.

### scan_jsonl_rules.py (108 LOC)

Scans a Claude Code session JSONL to find how loaded rules appear in the data.

**Purpose:** Verify whether "Contents of" lines (indicating loaded CLAUDE.md / .claude/rules/*.md files) are present in the JSONL and in what message type/structure.

**Usage:**
```bash
python3 dev/display/scan_jsonl_rules.py
```

**Output:** All unique "Contents of" entries found, with message type, line number, and parsed rule name/scope.

**Status:** Concluded — confirmed that Session-JSONL contains NO rules/instructions data (Contents of: 0, system-reminder: 0, claudeMd: 0). InstructionsLoaded hook is the only viable Claude-infrastructure source. Superseded by jsonl_exploration/ suite for detailed structure analysis.

### screenshot_panes.py (142 LOC)

Captures all 10 tmux panes of a running Monitor_CC session (5 windows) and combines them into a single PNG screenshot.

**Purpose:** Visual feedback for Claude during development — Claude reads the PNG to verify pane content and layout.

**Usage:**
```bash
./venv/bin/python dev/display/screenshot_panes.py
./venv/bin/python dev/display/screenshot_panes.py --session monitor_cc_global
```

**Output:** `/tmp/monitor_cc_screenshot.png` — combined 5-window, 10-pane layout image.

**Dependencies:** `termshot` (`brew install homeport/tap/termshot`), `Pillow` (`pip install Pillow`)

### A_format_cache_tracker_proof.py (128 LOC)

**Purpose:** Differential proof harness for `format_cache_tracker` decomposition. Loads 10 real session JSONLs via `extract_cache_turns`, calls `format_cache_tracker(turns, pane_height, pane_width)` across 6 parameter combinations (2 heights × 3 widths), serializes the 5-tuple return as JSON, verifies byte-identical against baseline. Exercises `_render_expanded_call_lines`, `_compute_cache_viewport`, and `_fmt_rl_reset_time` transitively.

**Usage:**
```bash
# From project root
./venv/bin/python dev/display/A_format_cache_tracker_proof.py --mode capture
./venv/bin/python dev/display/A_format_cache_tracker_proof.py --mode verify
```

**Output:** `json/baseline_<timestamp>.json` — dict of `{session_stem_HxW: serialized_5tuple}` for 60 cases.

### test_hover_map.py (437 LOC)

**Purpose:** Synthetic + real-log assertion suite for expand-model line_map correctness — every visible row maps to exactly one phys_row, monotonic, no duplicates; plus a `render_messages` `len(lines) == len(keys)` pairing check for the stripped-span dual-color overlay path.

**Usage:**
```bash
./venv/bin/python dev/display/test_hover_map.py
```

**Output:** PASS/FAIL lines per assertion, `Results: N passed, M failed` summary; exits 1 on any failure.

**Note:** `test_stripped_msg_pair_alignment` sources real entries from `src/logs/dual_log/*_forwarded.jsonl` + sibling `*_stripped.jsonl` (newest-first glob, not a hardcoded filename) — reconstructs entries via `_parse_forwarded_log(..., keep_last=None)`, builds the stripped-span accumulator via `accumulate_dual_log`, and attaches `_stripped_spans`/`_injected_spans` + ownership-lookup dicts to entries exactly as `pane.py`'s `_refresh_proxy_data` does, so `render_messages` runs its real dual-color (`use_dual=True`) path. Gracefully skips (PASS, not FAIL) when no dual-log pair with stripped content exists in `src/logs/dual_log/` — an environment/data availability gap, not a code issue.

## Documentation Tree

- [jsonl_exploration/DOCS.md](jsonl_exploration/DOCS.md) — JSONL structure exploration suite (3 scripts, MD reports)
