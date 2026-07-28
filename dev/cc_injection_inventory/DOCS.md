# dev/cc_injection_inventory/

## Purpose

Reusable audit tool that produces a COMPLETE INVENTORY of every distinguishable text class
present in the raw request payloads Claude Code sends, as captured in `src/logs/dual_log/`.
An inventory, not a top-N filter: every class found is listed regardless of frequency or size.
Answers "what text classes exist and are any of them unhandled?" — complements
`dev/proxy_dual_log/attribution_coverage.py`, which answers "does every entry our proxy already
strips have a named function?" (that tool never sees content our proxy does NOT touch; this one
does, by classification rather than log-diff).

## Modules

### cc_injection_inventory.py (712 LOC)

**Purpose:** Streams `src/logs/dual_log/*_original.jsonl`, extracts every text segment
(`system[0..3]`, message `content` — plain string / `text` blocks / `tool_result` content),
dedups by exact segment text, and classifies each distinct segment into one of 4 origin labels:
`COVERED` (an existing `src/proxy/strip_*.py` rule handles it — verified by actually running
`src/proxy/rules.py:apply_modification_rules` against a synthetic single-block message, not by
hardcoded markers), `KEEP` (audited + deliberately preserved: Read-tool truncation notice,
`<persisted-output>` wrapper, CLAUDE.md context SR), `OURS` (our own content — bash/tool output
bucketed by tool name via `tool_use_id` resolution, user prompts, assistant text), or
`UNCLASSIFIED` (CC-authored framing no rule touches and no prior audit judged — the category the
report leads with).

**Reads:** `src/logs/dual_log/api_requests_*_original.jsonl` (streamed line-by-line, never
loaded whole — the corpus includes a multi-GB file). Imports `src/proxy/rules.py`,
`strip_vocab.py`, `strip_sr.py`, `message_passes.py` via `sys.path.insert` + `import proxy.*`
(package-relative internal imports inside those modules resolve normally this way; avoids the
`block_dev_imports_src` hook's `from src.`/`import src.` literal-line block).

**Writes:** `dev/cc_injection_inventory/md/<YYYYMMDD>_cc_injection_inventory.md` (the report;
override name with `--out-name`). Console gets a 3-line summary only.

**Called by:** none (standalone CLI).

**Calls out:** none beyond the `src/proxy` imports above (stdlib only).

**Usage (from project root):**
```bash
./venv/bin/python dev/cc_injection_inventory/cc_injection_inventory.py
```

**CLI flags (all optional):**

| Flag | Description |
|---|---|
| `--logs-glob` | Override input glob (default: `<dual_log_dir>/api_requests_*_original.jsonl`, dual_log dir auto-resolved: local `src/logs/dual_log` if present, else 3 parents up from the worktree root — main repo) |
| `--out-name` | Override report filename (written under `md/`) |
| `--max-entries` | Debug: cap entries processed per file |

**Runtime:** ~11s for the full corpus (704 entries, ~4GB total, one file 3.9GB) on the reference
run — dominated by JSON parsing; classification itself is cheap because exact-text dedup means
the (expensive) real strip-pipeline call only runs once per distinct segment, never per raw
occurrence.

---

## Methodology notes (see generated report for the full write-up)

- **Dedup key:** `(file, role, section, block_type, exact segment text)` — segment-granularity
  refinement of the prior `(file, exact full message content)` convention, so a message combining
  one repeated block with one new block credits only the new block as a new distinct occurrence.
- **tool_result vs top-level text.** `tool_result.content` is OUR tool's own return value — a
  `<system-reminder>` or CLAUDE.md-preamble literal appearing INSIDE it is quoted DATA (a fetched
  issue body, a `strings` dump, source containing the tag as a string), never a CC wrapper. The
  CLAUDE.md-preserve and leftover-SR extraction passes (`_extract_claudemd_blocks`,
  `_extract_leftover_sr_blocks`) therefore only run on top-level shapes (`_TOP_LEVEL_SHAPES` =
  `plain_string`/`text`) — anything matching inside `tool_result` content stays part of that
  segment's `OURS` residual instead of being pulled out as `KEEP`/`UNCLASSIFIED`.
- **Grouping:** COVERED = one rule code; KEEP = one known wrapper; OURS = one tool name or the
  single user/assistant-text bucket; UNCLASSIFIED = one normalized-template signature (paths/
  IDs/numbers -> placeholders). Top-level user text uses a two-phase pass: a normalized signature
  needs >=2 SUBSTANTIVELY DISTINCT variants at >=40 chars to count as a recurring CC template
  (`UNCLASSIFIED`). Distinctness is containment-collapsed (`_distinct_variant_count`): whitespace-
  only differences (a trailing-newline shape artifact observed mid-corpus) AND one variant being a
  verbatim substring of another (prefix/suffix/mid-string extension — one human message edited/
  resent as it grew, not a template recurring) both collapse to a single variant. Everything that
  doesn't clear the bar (singletons, short acks, collapsed pairs) folds into one `OURS` aggregate.
- **Known simplification:** `role=user` segments are tested independently per block, not as part
  of the full multi-block message — every strip pass gates only on a single block's own content,
  so this does not change any COVERED/KEEP decision, but is a deliberate divergence from
  production's whole-message pass loop.
- **Self-scan exclusion:** the default glob excludes THIS session's own worker log — any file
  matching `api_requests_worker_*` that also embeds the current task/worktree name
  (`_current_task_name`, detected from the `.claude/worktrees/<name>/` path) — since that file is
  written live while the script runs and would make the corpus non-reproducible mid-scan. Other
  (past/unrelated) worker session logs are NOT excluded. An explicit `--logs-glob` bypasses this
  entirely. Excluded files are listed in the report's Corpus section.

## Gotchas

- The dual_log directory is gitignored and lives only in the main repo (not copied into a
  worktree) — the auto-resolve fallback assumes the fixed `.claude/worktrees/<name>/` nesting
  (matches `dev/proxy_dual_log/attribution_coverage.py`'s precedent); pass `--logs-glob` with an
  absolute path if that assumption doesn't hold. The same nesting check drives the self-scan
  exclusion above — running the script directly from a non-worktree checkout disables it (no task
  name to match against), so nothing is excluded in that case.
- `system[2]`/`system[3]` are always fully replaced by the proxy regardless of content (verified:
  `_apply_system_passes` / `_strip_sys3` in `src/proxy/rules.py` and `content_strip.py`) — they
  get exactly one COVERED row each, not split by content. `system[0]`/`system[1]` are never
  touched anywhere in `src/proxy/*.py` (grepped) — always UNCLASSIFIED.
- `role=system` bare-content messages are unconditionally wiped by RS (`_apply_role_system_strip`)
  except the `[Truncated:` guard — this correctly classifies content that would otherwise map to
  a DIFFERENT rule (e.g. deferred-tools, file-modified) as COVERED via RS specifically, since RS
  fires before any content-specific check would matter; the report sub-clusters these by content
  signature for readability, not by the rule code they'd hit under the `role=user`+SR path.
