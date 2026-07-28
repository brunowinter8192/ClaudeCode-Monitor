"""
cc_injection_inventory.py — complete inventory of every distinguishable text class present
in raw Claude Code request payloads, as captured in the proxy dual-logs.

INVENTORY, not a filter: every class found gets a row, however rare or small. Each class is
labelled COVERED (existing strip rule handles it), KEEP (audited + deliberately preserved),
INJECTED (text the PROXY ITSELF adds — e.g. a background-task wake-up replacement, which then
round-trips back into a LATER request's history since CC persists what was actually sent), OURS
(our own content — bash/tool output, user prompts, assistant text), or UNCLASSIFIED (CC-authored
framing/notices no rule touches and no prior audit judged).

Usage (from project root):
    ./venv/bin/python dev/cc_injection_inventory/cc_injection_inventory.py

Output: dev/cc_injection_inventory/md/<YYYYMMDD>_injection_inventory.md
"""

# INFRASTRUCTURE
import argparse
import glob as globmod
import json
import re
import sys
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_WORKTREE_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(_WORKTREE_ROOT / "src"))

# From src/proxy/rules.py: real proxy strip pipeline — run against synthetic single-block
# messages to get ground-truth COVERED/removed-chunk decisions instead of hardcoded markers
import proxy.rules as rules
# From src/proxy/strip_vocab.py: rule-code <-> marker <-> full-name vocabulary (attribute_chunk)
import proxy.strip_vocab as strip_vocab
# From src/proxy/strip_sr.py: SR regexes + CLAUDE.md preserve-guard preamble
import proxy.strip_sr as strip_sr
# From src/proxy/message_passes.py: role=system truncation-notice marker
import proxy.message_passes as message_passes

_DEFAULT_GLOB = "api_requests_*_original.jsonl"

_UUID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
_HEXID_RE = re.compile(r'\b[0-9a-fA-F]{6,}\b')
_PATH_RE = re.compile(r'(?:/[\w.\-]+){2,}')
_NUM_RE = re.compile(r'\d+')
_WS_RE = re.compile(r'\s+')

_ORIGIN_ORDER = ("UNCLASSIFIED", "KEEP", "COVERED", "INJECTED", "OURS")

# A resolved classification hit for one segment occurrence.
# kind: 'CLASS' (goes straight into the registry) | 'PENDING' (deferred two-phase user-text resolution)
ResolvedHit = namedtuple("ResolvedHit", ["kind", "ref", "label", "origin", "chars", "sample"])


# ORCHESTRATOR

def inventory_workflow() -> None:
    args = _parse_args()
    log_files, excluded_files = _resolve_log_files(args.logs_glob)
    if not log_files:
        raise RuntimeError(f"No log files matched: {args.logs_glob}")

    registry: dict = {}
    pending_user_text: dict = {}
    dedup_seen: dict = {}
    file_stats = []
    counters = {"raw_segments": 0, "distinct_segments": 0, "raw_messages": 0, "distinct_messages": 0}
    msg_dedup_seen: set = set()

    for path in log_files:
        stats = _process_file(path, registry, pending_user_text, dedup_seen, counters, args.max_entries,
                               msg_dedup_seen)
        file_stats.append(stats)

    _finalize_pending_user_text(pending_user_text, registry)

    report = _build_report(registry, file_stats, counters, log_files, excluded_files)
    out_path = _write_report(report, args.out_name)
    _print_console_summary(registry, counters, out_path)


# FUNCTIONS

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--logs-glob", default=None,
                   help=f"Glob for input files (default: <dual_log_dir>/{_DEFAULT_GLOB})")
    p.add_argument("--out-name", default=None, help="Override report filename (under md/)")
    p.add_argument("--max-entries", type=int, default=None,
                   help="Debug: cap entries processed per file")
    return p.parse_args()


# Resolve the dual_log directory — local (main repo) or via the fixed worktree nesting
# (.claude/worktrees/<name>/ -> 3 parents up = main repo), matching dev/proxy_dual_log precedent.
def _default_log_dir() -> Path:
    local = _WORKTREE_ROOT / "src" / "logs" / "dual_log"
    if local.exists():
        return local
    fallback = _WORKTREE_ROOT.parents[2] / "src" / "logs" / "dual_log"
    if fallback.exists():
        return fallback
    raise RuntimeError(f"dual_log directory not found at {local} or {fallback}")


_WORKER_LOG_PREFIX = "api_requests_worker_"


# Task/worktree name if running inside .claude/worktrees/<name>/, else None. Used only to
# recognize (and exclude, default-glob path only) THIS session's own still-growing worker log —
# never applied when the user passes an explicit --logs-glob.
def _current_task_name() -> str | None:
    parent = _WORKTREE_ROOT.parent
    if parent.name == "worktrees" and parent.parent.name == ".claude":
        return _WORKTREE_ROOT.name
    return None


# A worker log file is THIS session's own (live, still being appended to as this script runs)
# iff it uses the worker naming convention AND embeds the current task/worktree name.
def _is_own_live_session_log(path: Path, task_name: str | None) -> bool:
    if task_name is None:
        return False
    return path.name.startswith(_WORKER_LOG_PREFIX) and task_name in path.name


# Returns (included_files, excluded_files) — excluded is always [] when logs_glob is explicit.
def _resolve_log_files(logs_glob: str | None) -> tuple:
    if logs_glob:
        return sorted(Path(p) for p in globmod.glob(logs_glob)), []
    all_files = sorted(_default_log_dir().glob(_DEFAULT_GLOB))
    task_name = _current_task_name()
    included, excluded = [], []
    for f in all_files:
        (excluded if _is_own_live_session_log(f, task_name) else included).append(f)
    return included, excluded


# Stream one dual-log file, extracting + classifying every segment; returns per-file corpus stats
def _process_file(path: Path, registry: dict, pending: dict, dedup_seen: dict, counters: dict,
                   max_entries: int | None, msg_dedup_seen: set) -> dict:
    n_entries = 0
    n_messages = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if max_entries is not None and n_entries >= max_entries:
                break
            entry = json.loads(line)
            n_entries += 1
            payload = entry.get("payload", {}) or {}
            tool_names = _build_tool_name_map(payload.get("messages", []) or [])

            for idx, block in enumerate(payload.get("system", []) or []):
                if not isinstance(block, dict) or block.get("type") != "text":
                    continue
                text = block.get("text", "")
                if not text:
                    continue
                key = (path.name, "system", idx, text)
                _process_segment_occurrence(key, dedup_seen, registry, pending, counters,
                                             role=None, section="system", block_type=f"system[{idx}]",
                                             text=text, tool_name=None, sys_idx=idx)

            for msg in payload.get("messages", []) or []:
                n_messages += 1
                role = msg.get("role")
                content = msg.get("content")
                counters["raw_messages"] += 1
                msg_key = (path.name, role, content if isinstance(content, str)
                           else json.dumps(content, sort_keys=True, default=str))
                if msg_key not in msg_dedup_seen:
                    msg_dedup_seen.add(msg_key)
                    counters["distinct_messages"] += 1
                if isinstance(content, str):
                    if not content:
                        continue
                    key = (path.name, role, "plain_string", content)
                    _process_segment_occurrence(key, dedup_seen, registry, pending, counters,
                                                 role=role, section="messages", block_type="plain_string",
                                                 text=content, tool_name=None)
                elif isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            if not text:
                                continue
                            key = (path.name, role, "text", text)
                            _process_segment_occurrence(key, dedup_seen, registry, pending, counters,
                                                         role=role, section="messages", block_type="text",
                                                         text=text, tool_name=None)
                        elif btype == "tool_result":
                            tname = tool_names.get(block.get("tool_use_id"))
                            inner = block.get("content")
                            if isinstance(inner, str):
                                if not inner:
                                    continue
                                key = (path.name, role, "tool_result_str", inner)
                                _process_segment_occurrence(key, dedup_seen, registry, pending, counters,
                                                             role=role, section="messages",
                                                             block_type="tool_result_str", text=inner,
                                                             tool_name=tname)
                            elif isinstance(inner, list):
                                for sub in inner:
                                    if not (isinstance(sub, dict) and sub.get("type") == "text"):
                                        continue
                                    stext = sub.get("text", "")
                                    if not stext:
                                        continue
                                    key = (path.name, role, "tool_result_text", stext)
                                    _process_segment_occurrence(key, dedup_seen, registry, pending, counters,
                                                                 role=role, section="messages",
                                                                 block_type="tool_result_text", text=stext,
                                                                 tool_name=tname)
                        # tool_use / image / document — out of scope, skipped

    return {"file": path.name, "entries": n_entries, "messages": n_messages,
            "size_bytes": path.stat().st_size}


# tool_use_id -> tool name, rebuilt per-entry from all assistant tool_use blocks in that snapshot
def _build_tool_name_map(messages: list) -> dict:
    m = {}
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tid, name = block.get("id"), block.get("name")
                if tid and name:
                    m[tid] = name
    return m


# Dispatch one segment occurrence: replay cached classification on a dedup repeat (chars-only),
# classify fresh on first sight (registers count + chars + sample).
def _process_segment_occurrence(key, dedup_seen: dict, registry: dict, pending: dict, counters: dict,
                                 role, section, block_type, text, tool_name, sys_idx=None) -> None:
    counters["raw_segments"] += 1
    if key in dedup_seen:
        for kind, ref, chars in dedup_seen[key]:
            if kind == "CLASS":
                registry[ref]["chars"] += chars
            else:
                pending[ref]["chars"] += chars
        return
    counters["distinct_segments"] += 1
    hits = _classify_segment(role, section, block_type, text, tool_name, sys_idx)
    cache_entries = []
    for h in hits:
        if h.kind == "CLASS":
            _touch_class(registry, h.ref, h.label, h.origin, role, section, block_type, h.sample, h.chars)
        else:
            _touch_pending(pending, h.ref, role, section, block_type, h.sample, h.chars)
        cache_entries.append((h.kind, h.ref, h.chars))
    dedup_seen[key] = cache_entries


def _touch_class(registry, class_key, label, origin, role, section, block_type, sample, chars) -> None:
    rec = registry.get(class_key)
    if rec is None:
        registry[class_key] = {"label": label, "origin": origin, "role": role, "section": section,
                                "block_type": block_type, "count": 1, "chars": chars, "sample": sample}
    else:
        rec["count"] += 1
        rec["chars"] += chars


def _touch_pending(pending, sig, role, section, block_type, sample, chars) -> None:
    rec = pending.get(sig)
    if rec is None:
        pending[sig] = {"role": role, "section": section, "block_type": block_type,
                         "count": 1, "chars": chars, "sample": sample,
                         "variants": {(sample or "").strip()}}
    else:
        rec["count"] += 1
        rec["chars"] += chars
        rec["variants"].add((sample or "").strip())


# Route a fresh segment to the right classifier by (role, section)
def _classify_segment(role, section, block_type, text, tool_name, sys_idx) -> list:
    if section == "system":
        return _classify_system_segment(sys_idx, text)
    if role == "assistant":
        return [ResolvedHit("CLASS", "OURS:assistant_text", "Assistant response text", "OURS", len(text), text)]
    if role == "system":
        return _classify_role_system_segment(text)
    if role == "user":
        return _classify_user_segment(block_type, text, tool_name)
    return [ResolvedHit("CLASS", f"UNCLASSIFIED:role_{role}", f"Message role={role} content",
                         "UNCLASSIFIED", len(text), text)]


# system[] block — sys[2]/sys[3] are unconditionally fully replaced (COVERED); sys[0]/sys[1]
# are never touched by any proxy function (verified: grep for system[0]/system[1] mutation
# across src/proxy/*.py returns nothing) -> UNCLASSIFIED.
def _classify_system_segment(idx, text) -> list:
    if idx == 2:
        return [ResolvedHit("CLASS", "COVERED:SYS2_REPLACE",
                             "sys[2] CC agent system prompt — fully replaced by proxy rules (`_apply_system_passes`)",
                             "COVERED", len(text), text)]
    if idx == 3:
        return [ResolvedHit("CLASS", "COVERED:SYS3_REPLACE",
                             "sys[3] session/environment context block — fully replaced with '.' (`_strip_sys3`)",
                             "COVERED", len(text), text)]
    if idx == 0:
        return [ResolvedHit("CLASS", "UNCLASSIFIED:SYS0", "sys[0] billing header (x-anthropic-billing-header)",
                             "UNCLASSIFIED", len(text), text)]
    if idx == 1:
        return [ResolvedHit("CLASS", "UNCLASSIFIED:SYS1", 'sys[1] "You are Claude Code..." intro line',
                             "UNCLASSIFIED", len(text), text)]
    return [ResolvedHit("CLASS", f"UNCLASSIFIED:SYS{idx}", f"sys[{idx}] block (unexpected index in this corpus)",
                         "UNCLASSIFIED", len(text), text)]


# role=system message (message-level, bare content) — RS rule (_apply_role_system_strip) wipes
# ALL role=system content unconditionally, EXCEPT the Read-tool truncation notice (KEEP, guarded
# in production by `content.startswith('[Truncated:')`).
def _classify_role_system_segment(text) -> list:
    if text.startswith(message_passes._TRUNCATION_NOTICE_MARKER):
        return [ResolvedHit("CLASS", "KEEP:read_truncation_notice",
                             "Read-tool truncation notice (role=system, preserved by RS guard)",
                             "KEEP", len(text), text)]
    payload = {"system": [], "messages": [{"role": "system", "content": text}]}
    _, mods, *_ = rules.apply_modification_rules(payload)
    if "stripped_role_system_msg" in mods:
        sig = _normalize_template(text)[:100]
        class_key = f"COVERED:RS:{sig}"
        label = f'role=system message content — RS-covered ("{sig}")'
        return [ResolvedHit("CLASS", class_key, label, "COVERED", len(text), text)]
    return [ResolvedHit("CLASS", "UNCLASSIFIED:role_system_unhandled",
                         "role=system message content that RS did not fire on (unexpected)",
                         "UNCLASSIFIED", len(text), text)]


# Content shapes where CC genuinely delivers top-level framing/wrappers (plain user-typed text
# or a CC-appended text block). tool_result content is OUR tool's own return value — an SR-looking
# literal inside it is quoted DATA (a fetched issue body, a `strings` dump, RAG content, source
# code containing the tag as a string), never a CC-injected wrapper, so the CLAUDE.md-preserve and
# leftover-SR extraction below must not run against tool_result content.
_TOP_LEVEL_SHAPES = ("plain_string", "text")


# role=user segment — run the real proxy strip pipeline on a synthetic single-block message,
# then peel off KEEP wrappers / leftover unmatched SR blocks from the residual, then bucket
# whatever's left as OURS (tool/user content) or defer top-level text for two-phase resolution.
def _classify_user_segment(block_type, text, tool_name) -> list:
    content = _wrap_content(block_type, text)
    payload = {"system": [], "messages": [{"role": "user", "content": content}]}
    modified, mods, _orig2, _idxs, _origs, removed, injected, _ops = rules.apply_modification_rules(payload)
    residual = _unwrap_content(block_type, modified["messages"][0]["content"])
    removed_chunks = removed.get(0, []) if removed else []
    injected_chunks = injected.get(0, []) if injected else []

    hits = []
    for chunk in removed_chunks:
        if not chunk:
            continue
        code = strip_vocab.attribute_chunk(chunk) or "ALL"
        rule_name = strip_vocab.RULES.get(code, ("unattributed_strip", []))[0]
        hits.append(ResolvedHit("CLASS", f"COVERED:{code}", f"`{rule_name}` (rule {code})",
                                 "COVERED", len(chunk), chunk))

    # Text the PROXY ITSELF added (e.g. TN/BGK wake-up replacement) — ground truth is the
    # pipeline's own injected_msg_added output, same principle as removed_chunks for COVERED.
    # It round-trips back into a LATER request's history (CC persists what was actually sent,
    # not what CC intended) and would otherwise misread as a CC-authored recurring template.
    # Subtracted from residual so it isn't ALSO counted as OURS/UNCLASSIFIED below.
    for chunk in injected_chunks:
        if not chunk or chunk not in residual:
            continue
        residual = residual.replace(chunk, "", 1)
        sig = _normalize_template(chunk)[:100]
        hits.append(ResolvedHit("CLASS", f"INJECTED:{sig}", f'Proxy-injected text ("{sig}")',
                                 "INJECTED", len(chunk), chunk))

    if "stripped_po_preview" in mods:
        wrapper_text = residual.strip()
        hits.append(ResolvedHit("CLASS", "KEEP:po_wrapper",
                                 "<persisted-output> wrapper (Preview stripped by PP rule, wrapper kept)",
                                 "KEEP", len(wrapper_text), wrapper_text))
        return hits  # PO block content is entirely the wrapper; nothing else to classify

    if not residual or residual.strip() in ("", "."):
        return hits

    if block_type in _TOP_LEVEL_SHAPES:
        claude_blocks, residual = _extract_claudemd_blocks(residual)
        for cb in claude_blocks:
            hits.append(ResolvedHit("CLASS", "KEEP:claudemd_context",
                                     "CLAUDE.md context block (SR, preserve-guarded in strip_sr.py)",
                                     "KEEP", len(cb), cb))

        leftover_srs, residual = _extract_leftover_sr_blocks(residual)
        for sr in leftover_srs:
            sig = _normalize_template(sr)[:100]
            hits.append(ResolvedHit("CLASS", f"UNCLASSIFIED:sr:{sig}",
                                     f'Unmatched <system-reminder> block ("{sig}")',
                                     "UNCLASSIFIED", len(sr), sr))

        if not residual or residual.strip() in ("", "."):
            return hits

    if block_type in ("tool_result_str", "tool_result_text"):
        tname = tool_name or "(unresolved tool)"
        hits.append(ResolvedHit("CLASS", f"OURS:tool_result:{tname}", f"Tool result output — {tname}",
                                 "OURS", len(residual), residual))
    else:
        sig = _normalize_template(residual)[:120]
        hits.append(ResolvedHit("PENDING", sig, None, None, len(residual), residual))

    return hits


def _wrap_content(block_type, text):
    if block_type == "plain_string":
        return text
    if block_type == "text":
        return [{"type": "text", "text": text}]
    if block_type == "tool_result_str":
        return [{"type": "tool_result", "tool_use_id": "synthetic", "content": text}]
    if block_type == "tool_result_text":
        return [{"type": "tool_result", "tool_use_id": "synthetic", "content": [{"type": "text", "text": text}]}]
    raise ValueError(f"unknown block_type {block_type}")


def _unwrap_content(block_type, content) -> str:
    if block_type == "plain_string":
        return content if isinstance(content, str) else ""
    if not isinstance(content, list) or not content:
        return ""
    blk = content[0]
    if not isinstance(blk, dict):
        return ""
    if block_type == "text":
        return blk.get("text", "")
    if block_type == "tool_result_str":
        inner = blk.get("content", "")
        return inner if isinstance(inner, str) else ""
    if block_type == "tool_result_text":
        inner = blk.get("content", [])
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return inner[0].get("text", "")
        return ""
    return ""


# Peel out CLAUDE.md-context SR blocks (strip_sr._PRESERVE_PREAMBLE guard) from residual text.
# Only called for top-level shapes (see `_TOP_LEVEL_SHAPES`) — CLAUDE.md context is delivered as
# its own top-level message block, never nested inside a tool_result's own content.
def _extract_claudemd_blocks(text: str) -> tuple:
    kept = []

    def _repl(m):
        full = m.group(0)
        inner_m = strip_sr._INNER_SR_RE.search(full)
        inner = inner_m.group(1).strip() if inner_m else ""
        if inner.startswith(strip_sr._PRESERVE_PREAMBLE):
            kept.append(full)
            return ""
        return full

    new_text = strip_sr._STANDALONE_SR_RE.sub(_repl, text)
    return kept, new_text


# Any <system-reminder> block still standing after the full pipeline matched no known template —
# a genuine gap: proxy strips nothing here, no strip_vocab entry exists for it. Only called for
# top-level shapes (see `_TOP_LEVEL_SHAPES`) — inside tool_result this would be quoted OUR data,
# not a CC wrapper.
def _extract_leftover_sr_blocks(text: str) -> tuple:
    blocks = strip_sr._STANDALONE_SR_RE.findall(text)
    if not blocks:
        return [], text
    return blocks, strip_sr._STANDALONE_SR_RE.sub("", text)


# Normalize variable data (ids/paths/numbers) to placeholders for template-signature grouping
def _normalize_template(text: str) -> str:
    t = _UUID_RE.sub("<UUID>", text)
    t = _PATH_RE.sub("<PATH>", t)
    t = _HEXID_RE.sub("<HEX>", t)
    t = _NUM_RE.sub("#", t)
    return _WS_RE.sub(" ", t).strip()


# Collapse variants where one is a verbatim substring of another (prefix, suffix, or mid-string
# extension) before counting distinctness — a message a human edited/extended between two sends
# is still ONE evolving message, not two occurrences of a recurring CC template. Longest-first so
# a shorter variant merges into whichever longer kept variant already contains it.
def _distinct_variant_count(variants: set) -> int:
    ordered = sorted((v for v in variants if v), key=len, reverse=True)
    kept: list = []
    for v in ordered:
        if not any(v in longer for longer in kept):
            kept.append(v)
    return len(kept)


# Two-phase resolution for top-level user text: signatures with >=2 SUBSTANTIVELY DISTINCT
# variants (containment-collapsed, see `_distinct_variant_count`) are CC-authored templates
# humans don't retype verbatim -> UNCLASSIFIED, one row each. Everything else (singletons, and
# same-message-grew-longer pairs collapsing to 1 distinct variant) is genuinely unique -> folded
# into one OURS aggregate row (enumerating each would be a laundry-list, not a class).
def _finalize_pending_user_text(pending: dict, registry: dict) -> None:
    singleton_count = singleton_chars = 0
    singleton_sample = None
    for sig, stat in pending.items():
        if _distinct_variant_count(stat["variants"]) >= 2 and len(stat["sample"] or "") >= 40:
            registry[f"UNCLASSIFIED:user_text:{sig}"] = {
                "label": f'Recurring unattributed user-message text ("{sig}")',
                "origin": "UNCLASSIFIED", "role": stat["role"], "section": stat["section"],
                "block_type": stat["block_type"], "count": stat["count"], "chars": stat["chars"],
                "sample": stat["sample"],
            }
        else:
            singleton_count += stat["count"]
            singleton_chars += stat["chars"]
            if singleton_sample is None:
                singleton_sample = stat["sample"]
    if singleton_count:
        registry["OURS:user_typed_message"] = {
            "label": "User typed message (unique one-off text, no recurring template detected)",
            "origin": "OURS", "role": "user", "section": "messages", "block_type": "text/plain_string",
            "count": singleton_count, "chars": singleton_chars, "sample": singleton_sample,
        }


def _truncate(s: str, n: int = 160) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "…"


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def _build_report(registry: dict, file_stats: list, counters: dict, log_files: list,
                   excluded_files: list) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# CC Injection Inventory — {ts}",
        "",
        "Complete inventory of every distinguishable text class present in the raw request",
        "payloads Claude Code sends, as captured in `src/logs/dual_log/*_original.jsonl`. Every",
        "class found is listed regardless of frequency or size — this is an inventory, not a",
        "top-N ranking.",
        "",
    ]
    unclassified_rows = sorted(
        ((k, r) for k, r in registry.items() if r["origin"] == "UNCLASSIFIED"),
        key=lambda kr: -kr[1]["chars"],
    )
    lines += [
        "## Strip Candidates — CC-authored text no rule touches",
        "",
        'Direct answer to "what do we NOT strip today that should be stripped?" — every',
        "`UNCLASSIFIED` class (CC-authored, no existing rule fires on it, not previously",
        "audited/preserved), sorted by cumulative char cost. Same rows as the full `UNCLASSIFIED`",
        "table further down (role/section/block type/sample there) — nothing here is filtered out",
        "of the detailed tables below.",
        "",
        "| Class | Distinct occ. | Cum. chars |",
        "|---|---|---|",
    ]
    if unclassified_rows:
        for _key, r in unclassified_rows:
            lines.append(f"| {_md_escape(r['label'])} | {r['count']:,} | {r['chars']:,} |")
    else:
        lines.append("| *(none — every CC-authored class is already ruled on)* | — | — |")
    lines += [
        "",
        "## Methodology",
        "",
        "**Dedup metric.** Payloads are cumulative snapshots (each request re-sends the full",
        "conversation history), so a naive per-request scan overcounts by ~50x. Dedup key:",
        "`(file, role, section, block_type, exact segment text)` — a refinement of the prior",
        "codebase convention `(file, exact full message content)`, applied at SEGMENT granularity",
        "(one text/tool_result block, not the whole message) so a message that combines one",
        "repeated block with one genuinely new block correctly counts only the new block as a new",
        "distinct occurrence. A repeat (same file, same exact segment text) contributes to",
        "**cumulative char cost** (it is re-sent and re-billed every request) but not to",
        "**distinct occurrences** (it is the same real event, not a new one).",
        "",
        "**Segmentation.** Walks `system[0..3]` blocks, and every message's `content` — plain",
        "string, `text` blocks, and `tool_result` blocks (`.content` string or list of `{type:",
        "text}` sub-blocks). Does not descend into `tool_use.input`, `image`, or `document`",
        "blocks. `tool_result` segments are attributed to the originating tool by resolving",
        "`tool_use_id` against the preceding assistant `tool_use` block in the same payload.",
        "",
        "**Origin classification — 5 labels.** For every `role=user` and `role=system` segment, a",
        "synthetic single-block message is built matching the segment's real content shape and run",
        "through the REAL production pipeline (`src/proxy/rules.py:apply_modification_rules`) — no",
        "hardcoded marker lists. Chunks the pipeline actually REMOVES are attributed to a rule code",
        "via `strip_vocab.attribute_chunk` -> `COVERED`. Chunks the pipeline actually ADDS (the",
        "`injected_msg_added` return value — same ground-truth principle as removed-chunks for",
        "COVERED) -> `INJECTED`: text the PROXY ITSELF wrote, e.g. `strip_bg_completed.py`'s",
        "`_WAKEUP_TEXT` replacing a `<task-notification>`/background-exit block. This text then",
        "round-trips back into a LATER request's history — CC persists what was actually sent over",
        "the wire, not what CC intended — so without this label it would misread as a CC-authored",
        "recurring template. The 3 known preserve-guarded cases (Read-tool truncation notice,",
        "`<persisted-output>` wrapper, CLAUDE.md context SR) are detected explicitly on the",
        "pipeline's residual output -> `KEEP`. `role=assistant` text is never touched by any pass",
        "(verified: no `_apply_*` pass in `rules.py` gates on `role=='assistant'`) -> `OURS`",
        "directly.",
        "",
        "**tool_result vs top-level text — the enclosing shape decides, not the bytes.**",
        "`tool_result.content` is OUR tool's own return value (bash/git/file output, retrieved",
        "documents) — a `<system-reminder>` or CLAUDE.md-preamble literal appearing INSIDE it is",
        "quoted DATA (a fetched issue body, a `strings` dump of the CC binary, source containing the",
        "tag as a string), never a CC-injected wrapper, so the CLAUDE.md-preserve and leftover-SR",
        "extraction passes only run on top-level shapes (`plain_string` / `text` blocks) — any such",
        "literal inside `tool_result` content stays part of that segment's `OURS` residual, bucketed",
        "by tool name like the rest of the tool's output. On a top-level shape, a leftover unmatched",
        "`<system-reminder>` block after the full pipeline IS a genuine gap (no strip_vocab entry",
        "exists for it) -> `UNCLASSIFIED`. Remaining `tool_result` residual (not otherwise KEEP/",
        "COVERED) is `OURS`, bucketed by tool name.",
        "",
        "Remaining top-level user text uses a two-phase signature check: a normalized-text",
        "signature (>=40 chars) needs >=2 SUBSTANTIVELY DISTINCT underlying variants to count as a",
        "recurring CC template -> `UNCLASSIFIED`. Distinctness collapses two kinds of false",
        "recurrence: (a) whitespace-only differences (a trailing-newline shape artifact observed",
        "mid-corpus), and (b) containment — one variant being a verbatim substring (prefix, suffix,",
        "or mid-string extension) of another, which is one human message edited/resent as it grew,",
        "not two occurrences of a template. Short recurring text (greetings/acks like \"done\",",
        "\"ok\"), whitespace/containment-collapsed pairs, and all singletons fold into one `OURS`",
        "aggregate (genuinely unique or naturally-repeated human prose). `system[2]`/",
        "`system[3]` are unconditionally fully replaced by the proxy (`_apply_system_passes` /",
        "`_strip_sys3`) -> `COVERED`; `system[0]`/`system[1]` are never touched by any proxy",
        "function -> `UNCLASSIFIED`.",
        "",
        "**Grouping.** A class = one rule code (COVERED), one known wrapper (KEEP), one tool name",
        "or the single user/assistant-text bucket (OURS), or one normalized-template signature",
        "(INJECTED / UNCLASSIFIED) — variable data (paths, IDs, counts, timestamps) normalized to",
        "placeholders before signature comparison so e.g. 50 differently-IDed background-launch",
        "acks group into one row.",
        "",
        "**Known simplification:** role=user segments are tested independently per block (not as",
        "part of the full multi-block message) — message-level gates that only look at a single",
        "block's own content (all strip passes here) are unaffected; this does not change any",
        "COVERED/KEEP decision in this corpus.",
        "",
        "**Self-scan exclusion.** The default glob excludes THIS session's own worker log",
        "(`api_requests_worker_*` embedding the current task/worktree name) — that file is written",
        "live while the script runs, so including it would make the corpus non-reproducible",
        "mid-scan. An explicit `--logs-glob` is never filtered. Any file excluded this run is listed",
        "below.",
        "",
        "## Corpus",
        "",
        "| File | Entries | Messages (raw) | Size |",
        "|---|---|---|---|",
    ]
    total_entries = total_messages = total_size = 0
    for fs in file_stats:
        total_entries += fs["entries"]
        total_messages += fs["messages"]
        total_size += fs["size_bytes"]
        lines.append(f"| `{fs['file']}` | {fs['entries']} | {fs['messages']} | {_fmt_bytes(fs['size_bytes'])} |")
    lines.append(f"| **Total** | **{total_entries}** | **{total_messages}** | **{_fmt_bytes(total_size)}** |")
    if excluded_files:
        lines += ["", "**Excluded (own live worker session, default glob only):**"]
        lines += [f"- `{f.name}`" for f in excluded_files]
    lines += [
        "",
        "**Chosen metric — segments** (one text/tool_result block, used for all class counts below):",
        f"raw {counters['raw_segments']:,} / distinct {counters['distinct_segments']:,} "
        f"({counters['raw_segments'] / max(counters['distinct_segments'], 1):.1f}x overcount)  ",
        "**Prior codebase metric — whole messages** `(file, exact full message content)`, for comparison:",
        f"raw {counters['raw_messages']:,} / distinct {counters['distinct_messages']:,} "
        f"({counters['raw_messages'] / max(counters['distinct_messages'], 1):.1f}x overcount)",
        "",
    ]

    total_count = sum(r["count"] for r in registry.values())
    total_chars = sum(r["chars"] for r in registry.values())
    by_origin_n = {o: 0 for o in _ORIGIN_ORDER}
    by_origin_chars = {o: 0 for o in _ORIGIN_ORDER}
    for r in registry.values():
        by_origin_n[r["origin"]] += 1
        by_origin_chars[r["origin"]] += r["chars"]

    lines += [
        "## Summary",
        "",
        f"**Total classes:** {len(registry)}  |  **Total distinct occurrences:** {total_count:,}  "
        f"|  **Total cumulative chars:** {total_chars:,}",
        "",
        "| Origin | Classes | Distinct occurrences | Cumulative chars |",
        "|---|---|---|---|",
    ]
    for o in _ORIGIN_ORDER:
        n_cls = by_origin_n[o]
        n_occ = sum(r["count"] for r in registry.values() if r["origin"] == o)
        lines.append(f"| `{o}` | {n_cls} | {n_occ:,} | {by_origin_chars[o]:,} |")

    for origin in _ORIGIN_ORDER:
        rows = [(k, r) for k, r in registry.items() if r["origin"] == origin]
        rows.sort(key=lambda kr: -kr[1]["chars"])
        lines += [
            "",
            f"## {origin} ({len(rows)} class{'es' if len(rows) != 1 else ''})",
            "",
            "| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |",
            "|---|---|---|---|---|---|---|",
        ]
        for key, r in rows:
            role_s = r["role"] or "—"
            sample = _md_escape(_truncate(r["sample"] or ""))
            label = _md_escape(r["label"])
            lines.append(f"| {label} | `{role_s}` | `{r['section']}` | `{r['block_type']}` | "
                         f"{r['count']:,} | {r['chars']:,} | `{sample}` |")

    return "\n".join(lines) + "\n"


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _write_report(report: str, out_name: str | None) -> Path:
    md_dir = _SCRIPT_DIR / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    if out_name:
        out_path = md_dir / out_name
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = md_dir / f"{ts}_cc_injection_inventory.md"
    out_path.write_text(report, encoding="utf-8")
    return out_path


def _print_console_summary(registry: dict, counters: dict, out_path: Path) -> None:
    by_origin = {o: 0 for o in _ORIGIN_ORDER}
    for r in registry.values():
        by_origin[r["origin"]] += 1
    print(f"Classes: {len(registry)} total — " +
          ", ".join(f"{o}={by_origin[o]}" for o in _ORIGIN_ORDER))
    print(f"Segments: {counters['distinct_segments']:,} distinct / {counters['raw_segments']:,} raw "
          f"({counters['raw_segments'] / max(counters['distinct_segments'], 1):.1f}x overcount)")
    print(f"Report: {out_path}")


if __name__ == "__main__":
    inventory_workflow()
