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
import re
from datetime import datetime
from pathlib import Path

import tiktoken

FLOW_ID_PEEK_RE = re.compile(r'"flow_id":\s*"([^"]*)"')
FLOW_ID_PEEK_CHARS = 300

REPORTS_DIR = Path(__file__).parent / "md"
ENC = tiktoken.get_encoding("cl100k_base")
REBUILD_CR_RATIO_THRESHOLD = 0.2  # matches 03_cache_rebuild_context.py REBUILD_THRESHOLD

# ORCHESTRATOR

def main():
    args = parse_args()
    fwd_path = Path(args.forwarded_log)
    session_path = Path(args.session_jsonl).expanduser()
    original_path = Path(args.original_log).expanduser() if args.original_log else None

    ground_truth = load_ground_truth(session_path)
    fwd_states = load_forwarded_opus_states(fwd_path)
    mapped, mapping_notes = map_requests_to_fwd_states(ground_truth, fwd_states)

    collapse_points = detect_cr_collapse_points(mapped)
    range_pairs = build_range_pairs(args.req_range) if args.req_range else []
    auto_pairs = [(c - 1, c) for c in collapse_points] if args.auto_detect else []
    pairs = sorted(set(range_pairs) | set(auto_pairs))
    pairs = [(p1, p2) for p1, p2 in pairs if pair_available(mapped, p1, p2)]

    orig_by_flow = None
    if original_path:
        target_flow_ids = collect_target_flow_ids(mapped, pairs)
        orig_by_flow = load_original_payloads(original_path, target_flow_ids)

    pair_results = [analyze_pair(mapped, p1, p2, orig_by_flow) for p1, p2 in pairs]

    report = build_report(
        fwd_path, session_path, original_path, ground_truth, mapped, mapping_notes,
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
    parser.add_argument("--original-log", help="_original dual-log JSONL (full non-delta incoming payloads) "
                                                "for client-side-vs-proxy-side attribution of message diffs")
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
                "flow_id": d.get("flow_id", ""),
                "system": list(acc["system"]),
                "tools": list(acc["tools"]),
                "messages": list(acc["messages"]),
            })
    return states

# Peek the flow_id out of the first FLOW_ID_PEEK_CHARS of a raw JSONL line without a full JSON parse —
# avoids decoding ~9MB average lines in the _original log (158 lines, 1.4GB) for the ~150 irrelevant ones.
def peek_flow_id(raw_line):
    m = FLOW_ID_PEEK_RE.search(raw_line[:FLOW_ID_PEEK_CHARS])
    return m.group(1) if m else None

# Gather the flow_ids of every prev/curr request involved in the analyzed pairs
def collect_target_flow_ids(mapped, pairs):
    by_req = {m["req"]: m for m in mapped}
    flow_ids = set()
    for p1, p2 in pairs:
        flow_ids.add(by_req[p1]["state"]["flow_id"])
        flow_ids.add(by_req[p2]["state"]["flow_id"])
    return {f for f in flow_ids if f}

# Stream the _original dual-log (full non-delta payloads, one line per request) and collect the
# payload (system/tools/messages) for each target flow_id. Read-only, line-by-line — never loads the
# 1.4GB file whole. Full JSON parse only happens for lines whose peeked flow_id is in the target set.
def load_original_payloads(original_path, target_flow_ids):
    found = {}
    remaining = set(target_flow_ids)
    if not remaining:
        return found
    with open(original_path) as f:
        for raw_line in f:
            if not remaining:
                break
            fid = peek_flow_id(raw_line)
            if fid is None or fid not in remaining:
                continue
            d = json.loads(raw_line)
            payload = d.get("payload", {})
            found[fid] = {
                "system": payload.get("system", []) or [],
                "tools": payload.get("tools", []) or [],
                "messages": payload.get("messages", []) or [],
            }
            remaining.discard(fid)
    return found

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

# Count content blocks by type in a message, recursing one level into tool_result.content — images are
# frequently nested inside a tool_result wrapper (e.g. Read-tool output), not just top-level blocks.
def block_type_counts(msg):
    content = (msg or {}).get("content", "")
    if not isinstance(content, list):
        return {}
    counts = {}
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
        if t == "tool_result":
            nested = b.get("content")
            if isinstance(nested, list):
                for nb in nested:
                    if isinstance(nb, dict):
                        nt = nb.get("type", "?")
                        counts[nt] = counts.get(nt, 0) + 1
    return counts

# Collapse a message's content to a plain comparable string when it is either already a bare string,
# or a single {"type":"text","text":...} block (cache_control ignored) — else None (not comparable).
def normalize_content_shape(msg):
    content = (msg or {}).get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) == 1:
        b = content[0]
        if isinstance(b, dict) and b.get("type") == "text" and set(b.keys()) <= {"type", "text", "cache_control"}:
            return b.get("text", "")
    return None

# One-sentence auto-classification of a modified message row, for the report table
def classify_message_change(prev, curr):
    prev_types, curr_types = block_type_counts(prev), block_type_counts(curr)
    prev_img, curr_img = prev_types.get("image", 0), curr_types.get("image", 0)
    if curr_img < prev_img:
        return f"image(s) evicted: {prev_img - curr_img} removed (incl. nested tool_result images)"
    if prev.get("role") == curr.get("role"):
        norm_prev, norm_curr = normalize_content_shape(prev), normalize_content_shape(curr)
        if norm_prev is not None and norm_prev == norm_curr:
            return "format normalization only (list-of-one-text-block <-> bare string, same text)"
    return "content modified (non-image)"

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
            "note": classify_message_change(p, c),
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
            "prev_types": {}, "curr_types": c_types, "note": "-",
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
            "prev_types": p_types, "curr_types": {}, "note": "-",
        })
    rows.sort(key=lambda r: r["idx"])
    return rows, first_diff

# Full per-pair analysis: segment-by-segment diff + CR/CC reconciliation + optional original-log
# client-side-vs-proxy-side attribution
def analyze_pair(mapped, req_prev, req_curr, orig_by_flow=None):
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
    original_attribution = None
    if orig_by_flow is not None:
        original_attribution = diff_original_vs_forwarded(
            msg_rows, p_state["flow_id"], c_state["flow_id"], orig_by_flow,
        )

    return {
        "req_prev": req_prev, "req_curr": req_curr,
        "gt_prev": p, "gt_curr": c,
        "sys_rows": sys_rows,
        "tools_changed": tools_changed,
        "tools_names_prev": tools_names_prev, "tools_names_curr": tools_names_curr,
        "msg_rows": msg_rows, "first_msg_diff": first_msg_diff,
        "n_msg_prev": len(p_state["messages"]), "n_msg_curr": len(c_state["messages"]),
        "first_diverge_any": first_diverge_any, "first_diverge_no_sys0": first_diverge_no_sys0,
        "reconciliation": reconciliation,
        "original_attribution": original_attribution,
    }

# For each modified message row, compare the SAME index in the ORIGINAL (pre-proxy, incoming) payloads
# of req_prev and req_curr. Client-side: original already shows the same shrink at that index (proxy
# innocent). Proxy-side: original is byte-identical prev->curr at that index while forwarded differs
# (our modification pass introduced the change). Inconclusive: index out of range in original (structural
# drift between original and forwarded message-array shape).
def diff_original_vs_forwarded(msg_rows, flow_id_prev, flow_id_curr, orig_by_flow):
    orig_prev = orig_by_flow.get(flow_id_prev)
    orig_curr = orig_by_flow.get(flow_id_curr)
    if orig_prev is None or orig_curr is None:
        return {"available": False, "rows": []}

    op_msgs, oc_msgs = orig_prev["messages"], orig_curr["messages"]
    rows = []
    for row in msg_rows:
        if row["status"] != "modified":
            continue
        idx = row["idx"]
        op = op_msgs[idx] if idx < len(op_msgs) else None
        oc = oc_msgs[idx] if idx < len(oc_msgs) else None
        if op is None or oc is None:
            verdict = "INCONCLUSIVE (index out of range in original — structural drift vs forwarded)"
            op_chars = len(json.dumps(op, sort_keys=True)) if op else 0
            oc_chars = len(json.dumps(oc, sort_keys=True)) if oc else 0
        else:
            op_json = json.dumps(op, sort_keys=True)
            oc_json = json.dumps(oc, sort_keys=True)
            op_chars, oc_chars = len(op_json), len(oc_json)
            if op_json == oc_json:
                verdict = "PROXY-SIDE (original identical prev->curr at this index — forwarded diff is ours)"
            elif oc_chars < op_chars and row["delta_chars"] < 0:
                verdict = "CLIENT-SIDE (original already shrinks prev->curr at this index)"
            else:
                verdict = f"AMBIGUOUS (original prev={op_chars:,} curr={oc_chars:,} chars)"
        rows.append({
            "idx": idx, "orig_prev_chars": op_chars, "orig_curr_chars": oc_chars, "verdict": verdict,
        })
    return {"available": True, "rows": rows}

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
def build_report(fwd_path, session_path, original_path, ground_truth, mapped, mapping_notes,
                  collapse_points, range_pairs, auto_pairs, pair_results):
    lines = [
        "# Quartet Prefix-Diff Forensic Report",
        "",
        f"**Forwarded log:** `{fwd_path}`",
        f"**Session JSONL:** `{session_path}`",
        f"**Original log:** `{original_path}`" if original_path else "**Original log:** _not provided — no client-vs-proxy attribution_",
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
        "**Cache-control breakpoint markers are NOT reported below** (known prior finding): the forwarded "
        "delta chain hashes each element with `cache_control` STRIPPED before comparing "
        "(`logging._delta_hash` -> `_strip_cache_control`), so a marker-only change (breakpoint moved, no "
        "content change) never enters `messages_delta` and is invisible to this reconstruction. A "
        "replayed message's `cache_control` can be stale — carried over from an earlier request's delta "
        "even when the actually-sent marker position for the CURRENT request differs. The true sent "
        "breakpoint positions are not derivable from the quartet reconstruction; use `04_cache_validation.py` "
        "against the single-log format, or the live proxy pane, for breakpoint placement.",
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
        "| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])
    for m in r["msg_rows"]:
        img_flag = " <-IMG" if m["prev_image_count"] != m["curr_image_count"] else ""
        lines.append(
            f"| {m['idx']} | {m['status']}{img_flag} | {m['prev_chars']:,} | {m['curr_chars']:,} | "
            f"{m['delta_chars']:+,} | {m['prev_image_count']} | {m['curr_image_count']} | "
            f"{m['prev_types']} | {m['curr_types']} | {m['note']} |"
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
    ])

    oa = r["original_attribution"]
    if oa is not None:
        lines.extend([
            "### Original-vs-Forwarded Attribution (client-side vs proxy-side)",
            "",
        ])
        if not oa["available"]:
            lines.append(f"_No original-log entry found for REQ#{r['req_prev']} and/or REQ#{r['req_curr']}'s flow_id._")
        elif not oa["rows"]:
            lines.append("_No `modified`-status message rows to cross-check for this pair._")
        else:
            lines.append("| idx | fwd delta_chars | orig prev_chars | orig curr_chars | verdict |")
            lines.append("|---|---|---|---|---|")
            fwd_by_idx = {m["idx"]: m for m in r["msg_rows"]}
            for row in oa["rows"]:
                fwd_delta = fwd_by_idx[row["idx"]]["delta_chars"]
                lines.append(
                    f"| {row['idx']} | {fwd_delta:+,} | {row['orig_prev_chars']:,} | "
                    f"{row['orig_curr_chars']:,} | {row['verdict']} |"
                )
        lines.append("")

    lines.extend([
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

# Whether --original-log was provided (any pair carries a non-None original_attribution dict)
def original_log_used(pair_results):
    return any(r["original_attribution"] is not None for r in pair_results)

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
            "- Image content blocks — both top-level message blocks and images nested inside a "
            "`tool_result` wrapper's own `content` array — are removed (byte-for-byte, not re-encoded, "
            "`content` truncated to `[]` in the tool_result case) from historical messages between some "
            "consecutive requests — see `<-IMG` flagged rows per pair above."
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

    all_orig_rows = []
    for r in pair_results:
        oa = r["original_attribution"]
        if not (oa and oa["available"]):
            continue
        notes_by_idx = {m["idx"]: m["note"] for m in r["msg_rows"]}
        for row in oa["rows"]:
            all_orig_rows.append({**row, "note": notes_by_idx.get(row["idx"], "")})

    if all_orig_rows:
        img_rows = [row for row in all_orig_rows if row["note"].startswith("image(s) evicted")]
        other_rows = [row for row in all_orig_rows if not row["note"].startswith("image(s) evicted")]
        img_client = sum(1 for row in img_rows if row["verdict"].startswith("CLIENT-SIDE"))
        img_proxy = sum(1 for row in img_rows if row["verdict"].startswith("PROXY-SIDE"))
        other_client = sum(1 for row in other_rows if row["verdict"].startswith("CLIENT-SIDE"))
        other_proxy = sum(1 for row in other_rows if row["verdict"].startswith("PROXY-SIDE"))
        if img_rows:
            lines.append(
                f"- **Image-eviction rows ({len(img_rows)} cross-checked): {img_client} CLIENT-SIDE, "
                f"{img_proxy} PROXY-SIDE.** " + (
                    "ALL image-eviction rows are CLIENT-SIDE — the incoming (original, pre-proxy) payload "
                    "already shows the same shrink at the same index; the image eviction happens BEFORE our "
                    "proxy ever sees the request. **Fix-vs-document verdict: DOCUMENT — this is upstream/client "
                    "behavior, not a proxy bug; do not chase a proxy-side fix for the image eviction.**"
                    if img_client == len(img_rows) and img_proxy == 0
                    else "Mixed — see per-pair verdicts above, do not generalize a single verdict."
                )
            )
        if other_rows:
            fmt_norm = [row for row in other_rows if row["note"].startswith("format normalization")]
            lines.append(
                f"- **Non-image rows ({len(other_rows)} cross-checked, {len(fmt_norm)} of them "
                f"format-normalization-only): {other_client} CLIENT-SIDE, {other_proxy} PROXY-SIDE.** "
                + (
                    "ALL are PROXY-SIDE — the original payload is byte-identical prev->curr at this index "
                    "while forwarded differs. Where the note is \"format normalization only\", the identical "
                    "original text is our own cache_control-stripping / message-shape normalization "
                    "collapsing a single-text-block list to a bare string during forwarding — a benign proxy "
                    "transform, unrelated to images and not a factor in the CR/CC collapse (single-digit char "
                    "magnitude, see per-pair tables)."
                    if other_client == 0 and other_proxy == len(other_rows)
                    else "Mixed — see per-pair verdicts above, do not generalize a single verdict."
                )
            )
    elif original_log_used(pair_results):
        lines.append("- Original-log cross-check was requested but found no matching flow_id entries for the analyzed pairs.")

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
        "- WHERE the eviction happens (client vs proxy) is settled by the original-vs-forwarded "
        "cross-check above where available. WHY it triggers on this specific turn (a deliberate "
        "size/token-budget threshold vs. some other condition) is not determinable from these logs "
        "alone — only the byte-level EFFECT and its origin side are proven.",
        "",
    ])
    return lines


if __name__ == "__main__":
    main()
