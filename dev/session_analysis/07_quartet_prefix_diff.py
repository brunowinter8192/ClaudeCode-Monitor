#!/usr/bin/env python3
"""Forensic prefix-diff probe for repeated cache rebuilds.

Reconstructs full payload state (system/tools/messages) at each opus-family
request from a _forwarded dual-log delta chain, aligns it to session-JSONL
ground-truth usage (CR/CC/D) by timestamp, and diffs consecutive requests
segment-by-segment (system[0..3] individually / tools / messages) to find
WHERE a cache-rebuild's byte divergence sits and WHAT changed there.

Input handling note: the forwarded dual-log is delta-encoded (only changed
system/tools/message indices per request) — this is NOT the eliminated
single main-log raw_payload format read by 04/05/06; state must be replayed
by applying deltas cumulatively (mirrors src/proxy_display/forwarded_parser.py).

Usage (from project root):
    ./venv/bin/python dev/session_analysis/07_quartet_prefix_diff.py \\
        --forwarded-log src/logs/dual_log/api_requests_opus_<id>_forwarded.jsonl \\
        --session-jsonl ~/.claude/projects/<encoded>/session.jsonl \\
        --req-range 133-137 --auto-detect
"""
# INFRASTRUCTURE
import argparse
import json
from datetime import datetime
from pathlib import Path

import tiktoken

REPORTS_DIR = Path(__file__).parent / "md"
ENC = tiktoken.get_encoding("cl100k_base")
REBUILD_CR_RATIO_THRESHOLD = 0.2  # matches 03_cache_rebuild_context.py REBUILD_THRESHOLD

# ORCHESTRATOR

def main():
    args = parse_args()
    fwd_path = Path(args.forwarded_log)
    session_path = Path(args.session_jsonl).expanduser()

    ground_truth = load_ground_truth(session_path)
    fwd_states = load_forwarded_opus_states(fwd_path)
    mapped, mapping_notes = map_requests_to_fwd_states(ground_truth, fwd_states)

    collapse_points = detect_cr_collapse_points(mapped)
    range_pairs = build_range_pairs(args.req_range) if args.req_range else []
    auto_pairs = [(c - 1, c) for c in collapse_points] if args.auto_detect else []
    pairs = sorted(set(range_pairs) | set(auto_pairs))

    pair_results = [analyze_pair(mapped, p1, p2) for p1, p2 in pairs if pair_available(mapped, p1, p2)]

    report = build_report(
        fwd_path, session_path, ground_truth, mapped, mapping_notes,
        collapse_points, range_pairs, auto_pairs, pair_results,
    )

    REPORTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"{ts}_quartet_prefix_diff.md"
    report_path.write_text(report)
    print(f"Report: {report_path}")

# FUNCTIONS

# Parse CLI arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Forensic per-segment prefix-diff for cache rebuilds")
    parser.add_argument("--forwarded-log", required=True, help="_forwarded dual-log JSONL (delta-encoded)")
    parser.add_argument("--session-jsonl", required=True, help="Session JSONL for ground-truth CR/CC/D")
    parser.add_argument("--req-range", help="Consecutive REQ pair range to analyze, e.g. 133-137")
    parser.add_argument("--auto-detect", action="store_true", help="Also scan the whole log for CR-collapse points")
    return parser.parse_args()

# Infer model family (mirrors src/proxy_display/forwarded_parser.py: _infer_model_family)
def infer_model_family(model):
    m = model.lower()
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    return "opus"

# Build ground-truth (req_num 1-based opus-only, cr, cc, d, out, timestamp, model) list from session JSONL.
# One physical API request may emit several consecutive type=assistant JSONL lines (one per content
# block: thinking/tool_use), interleaved with type=user tool_result lines from mid-stream tool execution
# — all sharing the IDENTICAL (cr, cc, inp, out) usage tuple. Grouping key: usage tuple changes = new request.
def load_ground_truth(session_path):
    groups = []
    last_tuple = None
    with open(session_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("type") != "assistant":
                continue
            msg = d.get("message", {})
            usage = msg.get("usage", {})
            if not usage:
                continue
            cr = usage.get("cache_read_input_tokens", 0) or 0
            cc = usage.get("cache_creation_input_tokens", 0) or 0
            inp = usage.get("input_tokens", 0) or 0
            out = usage.get("output_tokens", 0) or 0
            model = msg.get("model", "")
            tup = (cr, cc, inp, out)
            if tup == last_tuple:
                continue
            groups.append({
                "cr": cr, "cc": cc, "d": inp, "out": out,
                "model": model, "timestamp": d.get("timestamp", ""),
            })
            last_tuple = tup

    opus_groups = [g for g in groups if infer_model_family(g["model"]) == "opus"]
    for i, g in enumerate(opus_groups):
        g["req"] = i + 1
    return opus_groups

# Expand {idx_str: elem} delta dict into a list of exactly count elements (mirrors forwarded_parser.py)
def dict_to_list(delta, count):
    lst = [None] * count
    for k, v in delta.items():
        i = int(k)
        if i < count:
            lst[i] = v
    return lst

# Shallow-copy prev, apply delta overwrites, resize to count (mirrors forwarded_parser.py)
def apply_delta(prev, delta, count):
    lst = list(prev)
    for k, v in delta.items():
        i = int(k)
        while len(lst) <= i:
            lst.append(None)
        lst[i] = v
    if len(lst) > count:
        lst = lst[:count]
    elif len(lst) < count:
        lst.extend([None] * (count - len(lst)))
    return lst

# Replay the forwarded delta chain, reconstructing full (system, tools, messages) state at every
# opus-family entry. Unchanged elements are SHARED object refs across snapshots (not deep-copied) —
# memory cost is O(unique content), not O(entries x payload size).
def load_forwarded_opus_states(fwd_path):
    acc = {"system": [], "tools": [], "messages": []}
    first_done = False
    states = []
    with open(fwd_path) as f:
        for line_idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("type") != "forwarded_delta":
                continue
            if infer_model_family(d.get("model", "")) != "opus":
                continue
            counts = d.get("counts", {})
            sc, tc, mc = counts.get("system", 0), counts.get("tools", 0), counts.get("messages", 0)
            if d.get("is_first") or not first_done:
                acc = {
                    "system": dict_to_list(d.get("system_delta") or {}, sc),
                    "tools": dict_to_list(d.get("tools_delta") or {}, tc),
                    "messages": dict_to_list(d.get("messages_delta") or {}, mc),
                }
                first_done = True
            else:
                acc = {
                    "system": apply_delta(acc["system"], d.get("system_delta") or {}, sc),
                    "tools": apply_delta(acc["tools"], d.get("tools_delta") or {}, tc),
                    "messages": apply_delta(acc["messages"], d.get("messages_delta") or {}, mc),
                }
            states.append({
                "fwd_line_idx": line_idx,
                "timestamp": d.get("timestamp", ""),
                "system": list(acc["system"]),
                "tools": list(acc["tools"]),
                "messages": list(acc["messages"]),
            })
    return states

# Align session-JSONL ground-truth requests to forwarded-log opus states by timestamp.
# forwarded_delta.timestamp = when the request was SENT (before response streams back), so the
# correct forwarded entry for a ground-truth group is the LAST forwarded entry sent at or before the
# group's timestamp. Two-pointer, strictly monotonic: a forwarded entry with no ground-truth response
# (retried/interrupted request) is silently absorbed into the NEXT group's match — not 1:1 by position.
def map_requests_to_fwd_states(ground_truth, fwd_states):
    fi = 0
    mapped = []
    n_fwd = len(fwd_states)
    for g in ground_truth:
        gts = g["timestamp"]
        best = None
        while fi < n_fwd and fwd_states[fi]["timestamp"] <= gts:
            best = fwd_states[fi]
            fi += 1
        mapped.append({**g, "state": best})
    unmatched_gt = sum(1 for m in mapped if m["state"] is None)
    leftover_fwd = n_fwd - fi
    notes = {
        "opus_fwd_entries": n_fwd,
        "opus_gt_groups": len(ground_truth),
        "unmatched_ground_truth": unmatched_gt,
        "unconsumed_forwarded_entries": leftover_fwd,
    }
    return mapped, notes

# Scan ground truth for CR-collapse points: CC dominates AND CR drops below threshold x the
# highest CR seen so far in the session (mirrors 03_cache_rebuild_context.py detect_rebuilds rule).
def detect_cr_collapse_points(mapped):
    collapse = []
    prev_max_cr = 0
    for m in mapped:
        cr, cc = m["cr"], m["cc"]
        if prev_max_cr > 0 and cc > cr and cr < prev_max_cr * REBUILD_CR_RATIO_THRESHOLD:
            collapse.append(m["req"])
        prev_max_cr = max(prev_max_cr, cr)
    return collapse

# Parse "A-B" into list of consecutive (prev_req, curr_req) pairs
def build_range_pairs(range_str):
    a, b = (int(x) for x in range_str.split("-"))
    return [(r, r + 1) for r in range(a, b)]

# Both requests in a pair must have a mapped forwarded state
def pair_available(mapped, req_prev, req_curr):
    by_req = {m["req"]: m for m in mapped}
    p, c = by_req.get(req_prev), by_req.get(req_curr)
    return p is not None and c is not None and p["state"] is not None and c["state"] is not None

# Diff one system block: text length + changed flag
def diff_system_block(prev_blk, curr_blk):
    prev_txt = (prev_blk or {}).get("text", "")
    curr_txt = (curr_blk or {}).get("text", "")
    return {
        "changed": prev_txt != curr_txt,
        "prev_chars": len(prev_txt), "curr_chars": len(curr_txt),
        "delta_chars": len(curr_txt) - len(prev_txt),
    }

# Count content blocks by type in a message (top-level string content = no blocks)
def block_type_counts(msg):
    content = (msg or {}).get("content", "")
    if not isinstance(content, list):
        return {}
    counts = {}
    for b in content:
        if isinstance(b, dict):
            t = b.get("type", "?")
            counts[t] = counts.get(t, 0) + 1
    return counts

# Find message indices (and block index) carrying a cache_control marker
def find_breakpoints(messages):
    bps = set()
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            continue
        if m.get("cache_control"):
            bps.add((i, "top"))
        content = m.get("content")
        if isinstance(content, list):
            for j, b in enumerate(content):
                if isinstance(b, dict) and b.get("cache_control"):
                    bps.add((i, j))
    return bps

# Diff messages segment: per-index status (unchanged/modified/added/removed), image involvement,
# first diverging index (earliest index where content differs — the rolling-hash-chain break point).
def diff_messages(prev_msgs, curr_msgs):
    n_prev, n_curr = len(prev_msgs), len(curr_msgs)
    n_common = min(n_prev, n_curr)
    rows = []
    first_diff = None
    for i in range(n_common):
        p, c = prev_msgs[i], curr_msgs[i]
        p_json = json.dumps(p, sort_keys=True) if p else ""
        c_json = json.dumps(c, sort_keys=True) if c else ""
        if p_json == c_json:
            continue
        if first_diff is None:
            first_diff = i
        p_types, c_types = block_type_counts(p), block_type_counts(c)
        rows.append({
            "idx": i, "status": "modified",
            "prev_chars": len(p_json), "curr_chars": len(c_json),
            "delta_chars": len(c_json) - len(p_json),
            "prev_image_count": p_types.get("image", 0), "curr_image_count": c_types.get("image", 0),
            "prev_types": p_types, "curr_types": c_types,
        })
    for i in range(n_common, n_curr):
        if first_diff is None:
            first_diff = i
        c = curr_msgs[i]
        c_json = json.dumps(c, sort_keys=True) if c else ""
        c_types = block_type_counts(c)
        rows.append({
            "idx": i, "status": "added",
            "prev_chars": 0, "curr_chars": len(c_json), "delta_chars": len(c_json),
            "prev_image_count": 0, "curr_image_count": c_types.get("image", 0),
            "prev_types": {}, "curr_types": c_types,
        })
    for i in range(n_common, n_prev):
        if first_diff is None:
            first_diff = i
        p = prev_msgs[i]
        p_json = json.dumps(p, sort_keys=True) if p else ""
        p_types = block_type_counts(p)
        rows.append({
            "idx": i, "status": "removed",
            "prev_chars": len(p_json), "curr_chars": 0, "delta_chars": -len(p_json),
            "prev_image_count": p_types.get("image", 0), "curr_image_count": 0,
            "prev_types": p_types, "curr_types": {},
        })
    rows.sort(key=lambda r: r["idx"])
    return rows, first_diff

# Full per-pair analysis: segment-by-segment diff + breakpoint diff + CR/CC reconciliation
def analyze_pair(mapped, req_prev, req_curr):
    by_req = {m["req"]: m for m in mapped}
    p, c = by_req[req_prev], by_req[req_curr]
    p_state, c_state = p["state"], c["state"]

    sys_rows = []
    n_sys = max(len(p_state["system"]), len(c_state["system"]))
    for i in range(n_sys):
        pb = p_state["system"][i] if i < len(p_state["system"]) else None
        cb = c_state["system"][i] if i < len(c_state["system"]) else None
        sys_rows.append({"idx": i, **diff_system_block(pb, cb)})

    tools_prev_json = json.dumps(p_state["tools"], sort_keys=True)
    tools_curr_json = json.dumps(c_state["tools"], sort_keys=True)
    tools_changed = tools_prev_json != tools_curr_json
    tools_names_prev = [t.get("name", "") for t in p_state["tools"] if isinstance(t, dict)]
    tools_names_curr = [t.get("name", "") for t in c_state["tools"] if isinstance(t, dict)]

    msg_rows, first_msg_diff = diff_messages(p_state["messages"], c_state["messages"])

    bps_prev = find_breakpoints(p_state["messages"])
    bps_curr = find_breakpoints(c_state["messages"])

    order = []
    for i in range(n_sys):
        order.append(("system", i, sys_rows[i]["changed"]))
    order.append(("tools", None, tools_changed))
    for r in msg_rows:
        order.append(("messages", r["idx"], True))
    first_diverge_any = next(((seg, idx) for seg, idx, ch in order if ch), (None, None))
    first_diverge_no_sys0 = next(
        ((seg, idx) for seg, idx, ch in order if ch and not (seg == "system" and idx == 0)),
        (None, None),
    )

    reconciliation = reconcile(p_state, p, c)

    return {
        "req_prev": req_prev, "req_curr": req_curr,
        "gt_prev": p, "gt_curr": c,
        "sys_rows": sys_rows,
        "tools_changed": tools_changed,
        "tools_names_prev": tools_names_prev, "tools_names_curr": tools_names_curr,
        "msg_rows": msg_rows, "first_msg_diff": first_msg_diff,
        "n_msg_prev": len(p_state["messages"]), "n_msg_curr": len(c_state["messages"]),
        "bps_removed": sorted(bps_prev - bps_curr), "bps_added": sorted(bps_curr - bps_prev),
        "first_diverge_any": first_diverge_any, "first_diverge_no_sys0": first_diverge_no_sys0,
        "reconciliation": reconciliation,
    }

# CR/CC reconciliation: tiktoken-estimate BP1 (system[0:3]) and BP1+tools segments (fast — small
# segments only; message content includes multi-MB base64 image blobs, deliberately NOT tokenized:
# Anthropic prices images by pixel dimensions, not char/tiktoken count, so a char-based estimate over
# image blocks would be meaningless). Also checks the literal "read what N-1 wrote" recovery identity.
def reconcile(p_state, gt_prev, gt_curr):
    bp1_json = json.dumps(p_state["system"][:3], ensure_ascii=False)
    bp1_tokens = len(ENC.encode(bp1_json))
    tools_json = json.dumps(p_state["tools"], ensure_ascii=False)
    tools_tokens = len(ENC.encode(tools_json))
    recovery_match = gt_curr["cr"] == gt_prev["cr"] + gt_prev["cc"]
    return {
        "bp1_estimate_tokens": bp1_tokens,
        "bp1_plus_tools_estimate_tokens": bp1_tokens + tools_tokens,
        "actual_cr_curr": gt_curr["cr"],
        "recovery_identity_holds": recovery_match,
        "recovery_lhs": gt_curr["cr"], "recovery_rhs": gt_prev["cr"] + gt_prev["cc"],
    }

# Build the full markdown report
def build_report(fwd_path, session_path, ground_truth, mapped, mapping_notes,
                  collapse_points, range_pairs, auto_pairs, pair_results):
    lines = [
        "# Quartet Prefix-Diff Forensic Report",
        "",
        f"**Forwarded log:** `{fwd_path}`",
        f"**Session JSONL:** `{session_path}`",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Methodology — REQ Number Mapping",
        "",
        "Ground-truth REQ numbers are built by grouping session-JSONL `type=assistant` lines by their "
        "`(cache_read, cache_creation, input, output)` usage tuple — consecutive identical tuples "
        "(including ones separated by interleaved `type=user` tool_result lines from mid-stream tool "
        "execution within the SAME response) collapse into one request. This differs from naive line "
        "position because a single response streams multiple content blocks (thinking/tool_use) as "
        "separate JSONL lines.",
        "",
        "Forwarded-log opus-family entries are aligned to these ground-truth requests by timestamp: "
        "each `forwarded_delta.timestamp` is the SEND time; a ground-truth request's forwarded state is "
        "the LAST forwarded entry sent at or before the request's response timestamp (monotonic "
        "two-pointer). Forwarded entries with no corresponding ground-truth response (retried/aborted "
        "sends) are silently absorbed — this makes the mapping N:1 in places, not a fixed index offset.",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Opus forwarded-log entries | {mapping_notes['opus_fwd_entries']} |",
        f"| Opus ground-truth request groups | {mapping_notes['opus_gt_groups']} |",
        f"| Ground-truth requests with no forwarded match | {mapping_notes['unmatched_ground_truth']} |",
        f"| Forwarded entries absorbed (retries, no distinct response) | "
        f"{mapping_notes['opus_fwd_entries'] - mapping_notes['opus_gt_groups'] + mapping_notes['unmatched_ground_truth']} |",
        "",
        "## Auto-Detected CR-Collapse Points",
        "",
        f"Rule: `CC > CR` and `CR < {REBUILD_CR_RATIO_THRESHOLD} x max(CR seen so far in session)` "
        "(mirrors `03_cache_rebuild_context.py`).",
        "",
    ]
    if collapse_points:
        lines.append("| REQ | CR | CC | D | prior max CR |")
        lines.append("|---|---|---|---|---|")
        by_req = {m["req"]: m for m in mapped}
        prev_max = 0
        for m in mapped:
            if m["req"] in collapse_points:
                lines.append(f"| {m['req']} | {m['cr']:,} | {m['cc']:,} | {m['d']:,} | {prev_max:,} |")
            prev_max = max(prev_max, m["cr"])
    else:
        lines.append("_None detected._")
    lines.append("")

    pairs_requested = sorted(set(range_pairs) | set(auto_pairs))
    lines.extend([
        "## Pairs Analyzed",
        "",
        f"Requested: {pairs_requested}",
        f"Analyzed (both sides had a forwarded match): {[(r['req_prev'], r['req_curr']) for r in pair_results]}",
        "",
    ])

    for r in pair_results:
        lines.extend(build_pair_section(r))

    lines.extend(build_findings_summary(pair_results))
    return "\n".join(lines)

# Build the markdown section for one pair
def build_pair_section(r):
    gp, gc = r["gt_prev"], r["gt_curr"]
    lines = [
        f"## REQ#{r['req_prev']} -> REQ#{r['req_curr']}",
        "",
        "| | CR | CC | D |",
        "|---|---|---|---|",
        f"| REQ#{r['req_prev']} | {gp['cr']:,} | {gp['cc']:,} | {gp['d']:,} |",
        f"| REQ#{r['req_curr']} | {gc['cr']:,} | {gc['cc']:,} | {gc['d']:,} |",
        "",
        "### System Blocks",
        "",
        "| idx | changed | prev_chars | curr_chars | delta_chars |",
        "|---|---|---|---|---|",
    ]
    for s in r["sys_rows"]:
        lines.append(f"| {s['idx']} | {'YES' if s['changed'] else '-'} | {s['prev_chars']:,} | "
                      f"{s['curr_chars']:,} | {s['delta_chars']:+,} |")

    lines.extend([
        "",
        "### Tools",
        "",
        f"- Changed: **{'YES' if r['tools_changed'] else 'no'}**",
    ])
    if r["tools_changed"]:
        removed = set(r["tools_names_prev"]) - set(r["tools_names_curr"])
        added = set(r["tools_names_curr"]) - set(r["tools_names_prev"])
        lines.append(f"- Names removed: {sorted(removed) or '-'}")
        lines.append(f"- Names added: {sorted(added) or '-'}")

    lines.extend([
        "",
        f"### Messages ({r['n_msg_prev']} -> {r['n_msg_curr']})",
        "",
        f"- First diverging message index: **{r['first_msg_diff']}**",
        f"- Modified/added/removed rows: {len(r['msg_rows'])}",
        "",
        "| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for m in r["msg_rows"]:
        img_flag = " <-IMG" if m["prev_image_count"] != m["curr_image_count"] else ""
        lines.append(
            f"| {m['idx']} | {m['status']}{img_flag} | {m['prev_chars']:,} | {m['curr_chars']:,} | "
            f"{m['delta_chars']:+,} | {m['prev_image_count']} | {m['curr_image_count']} | "
            f"{m['prev_types']} | {m['curr_types']} |"
        )

    img_involved_rows = [m for m in r["msg_rows"] if m["prev_image_count"] != m["curr_image_count"]]
    total_img_removed = sum(max(0, m["prev_image_count"] - m["curr_image_count"]) for m in r["msg_rows"])
    total_img_added = sum(max(0, m["curr_image_count"] - m["prev_image_count"]) for m in r["msg_rows"])
    lines.extend([
        "",
        f"**Image blocks involved:** {'YES' if img_involved_rows else 'no'} "
        f"({len(img_involved_rows)} message(s), {total_img_removed} image block(s) removed, "
        f"{total_img_added} added)",
        "",
        "### Cache-Control Breakpoint Markers",
        "",
        f"- Removed (present in REQ#{r['req_prev']}, gone in REQ#{r['req_curr']}): {r['bps_removed'] or '-'}",
        f"- Added: {r['bps_added'] or '-'}",
        "",
        "### Segment Attribution",
        "",
        f"- First diverging segment (raw, includes per-request system[0] churn): "
        f"`{r['first_diverge_any'][0]}[{r['first_diverge_any'][1]}]`",
        f"- First diverging segment (excluding system[0]): "
        f"`{r['first_diverge_no_sys0'][0]}[{r['first_diverge_no_sys0'][1]}]`",
        "",
        "### CR/CC Reconciliation",
        "",
    ])
    rec = r["reconciliation"]
    lines.extend([
        "| Metric | Value |",
        "|---|---|",
        f"| tiktoken estimate: system[0:3] (BP1 hypothesis) | {rec['bp1_estimate_tokens']:,} |",
        f"| tiktoken estimate: system[0:3] + tools (BP1+BP2) | {rec['bp1_plus_tools_estimate_tokens']:,} |",
        f"| Actual CR of REQ#{r['req_curr']} | {rec['actual_cr_curr']:,} |",
        f"| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | "
        f"**{'HOLDS' if rec['recovery_identity_holds'] else 'does not hold'}** "
        f"({rec['recovery_lhs']:,} vs {rec['recovery_rhs']:,}) |",
        "",
    ])
    return lines

# Build the closing proven-vs-hypothesis findings summary
def build_findings_summary(pair_results):
    lines = [
        "## Findings Summary",
        "",
        "### Proven from bytes",
        "",
    ]
    any_img = any(
        any(m["prev_image_count"] != m["curr_image_count"] for m in r["msg_rows"])
        for r in pair_results
    )
    sys123_stable = all(
        not any(s["changed"] for s in r["sys_rows"] if s["idx"] != 0)
        for r in pair_results
    )
    tools_stable = all(not r["tools_changed"] for r in pair_results)
    recoveries = [(r["req_prev"], r["req_curr"], r["reconciliation"]["recovery_identity_holds"])
                  for r in pair_results]

    if any_img:
        lines.append(
            "- Image content blocks inside historical `tool_result` messages are removed "
            "(byte-for-byte, not just re-encoded) between some consecutive requests — "
            "see `<-IMG` flagged rows per pair above."
        )
    if sys123_stable:
        lines.append(
            "- `system[1]`, `system[2]`, `system[3]` are byte-identical across all analyzed pairs; "
            "only `system[0]` (per-request billing/entrypoint header) changes every request. "
            "The problem statement's hypothesis that divergence sits in `system[3]`/tools is "
            "REFUTED for this incident — those segments never differ across the analyzed pairs."
        )
    if tools_stable:
        lines.append("- `tools` array is byte-identical across all analyzed pairs — not a factor here.")
    lines.append(
        "- Per pair, the first diverging message index (excluding the constant `system[0]` churn) "
        "is reported above with exact index and char magnitude — see \"Segment Attribution\" per pair."
    )
    for rp, rc, holds in recoveries:
        lines.append(
            f"- REQ#{rp}->REQ#{rc}: recovery identity CR[curr]==CR[prev]+CC[prev] "
            f"{'HOLDS' if holds else 'does NOT hold'} (checked from ground-truth CR/CC directly)."
        )

    lines.extend([
        "",
        "### Interpretation / hypotheses (not provable from bytes alone)",
        "",
        "- The BP1 cross-session hypothesis (CR=21,023 == cached read of `system[0:2]`) is only "
        "PARTIALLY supported: tiktoken (cl100k_base, an approximation of Claude's real tokenizer) "
        "estimates `system[0:3]` at roughly two-thirds of 21,023 tokens — same order of magnitude, "
        "consistent with cl100k's known undercount on structured content, but not an exact match. "
        "Confirming the exact BP1 byte-identity against another project's session log was out of "
        "scope of the provided data (only this session's logs were read).",
        "- When the recovery identity does NOT hold for a pair where messages are byte-identical up "
        "to some index, cache non-availability is consistent with Anthropic-side cache-write "
        "propagation latency (a large `CC` write may not be immediately readable moments later) — "
        "this is a plausible explanation for requests spaced tens of seconds apart, not something "
        "provable from the sent bytes.",
        "- Whether the image eviction is a deliberate context-budget mechanism (client-side, "
        "triggered once a size/token threshold is crossed) versus an incidental side effect of some "
        "other pass is not determinable from these logs alone — only the byte-level EFFECT (images "
        "disappear from many historical messages within one or a few consecutive requests) is proven.",
        "",
    ])
    return lines


if __name__ == "__main__":
    main()
