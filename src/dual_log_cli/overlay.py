# INFRASTRUCTURE
# From src/proxy_display/parser.py: the read-side dual-log accumulator the proxy pane uses. Reused
# rather than re-implemented, so duallog inherits its two hard-won behaviours unchanged — the
# per-coordinate span accumulation AND the write-side attribution lag correction
# (_lag_msg_idx_by_flow_id), which credits a trailing-msg total_tokens strip to the request that
# performed it instead of the one whose delta line happens to carry it.
from ..proxy_display.parser import accumulate_dual_log
# From timeline.py: {flow_id: REQ number}, the same numbering `msgs` prints
from .timeline import request_numbers_by_flow

# FUNCTIONS


# Build the strip/inject overlay for one session -> {(msg_idx, blk_idx): {stripped, injected, req}}.
#
# duallog is msg-centric where the delta streams are flow-centric, and the two meet without any
# scoping work: `expand` renders msgs of ONE payload (the last non-haiku `_original` request), so
# there is no request header a foreign flow's span could appear under — the pane's flow-scoping has
# no analogue here. What a msg needs is the CUMULATIVE state of its coordinate, which is exactly
# what `accumulate_dual_log` leaves in `acc['messages'][msg][blk]`.
#
# The content direction is inverted from the pane's: duallog shows the PRE-strip original, so
# `stripped` is the part of the very text on screen that the proxy removed, and `injected` is what
# it put there instead (text that appears nowhere in the displayed content).
#
# Attribution: the flow that RECORDED a coordinate is not always the one that stripped it, so the
# lag set wins where it applies. Measured on the recorded sessions: no coordinate is ever touched by
# more than one flow, so the owner is unambiguous.
def build_overlay(session: dict, family: str, boundaries: list) -> dict:
    streams = session["streams"]
    acc_stripped: dict = {}
    acc_injected: dict = {}
    if streams.get("stripped") is not None:
        accumulate_dual_log(streams["stripped"], 0, acc_stripped)
    if streams.get("injected") is not None:
        accumulate_dual_log(streams["injected"], 0, acc_injected)
    fam_s = acc_stripped.get(family, {})
    fam_i = acc_injected.get(family, {})
    numbers = request_numbers_by_flow(boundaries)
    owners = _owners_by_index(fam_s, fam_i)
    overlay: dict = {}
    for source, key in ((fam_s, "stripped"), (fam_i, "injected")):
        for msg_key, blocks in (source.get("messages") or {}).items():
            for blk_key, recorded in (blocks or {}).items():
                texts = _texts(recorded, key)
                if not texts:
                    continue
                slot = overlay.setdefault((int(msg_key), int(blk_key)), {
                    "stripped": [], "injected": [], "req": None,
                })
                slot[key] = texts
                if slot["req"] is None:
                    slot["req"] = numbers.get(owners.get(msg_key, ""))
    return overlay


# {msg_idx_str: flow_id} — which flow actually performed the transformation at each coordinate.
# The lag set takes precedence: it names the request that stripped the msg, while the raw set names
# whichever line recorded it (one request later for a trailing total_tokens nuke).
def _owners_by_index(fam_stripped: dict, fam_injected: dict) -> dict:
    owners: dict = {}
    for fam in (fam_stripped, fam_injected):
        for flow_id, indices in (fam.get("_msg_idx_by_flow_id") or {}).items():
            for index in indices:
                owners.setdefault(index, flow_id)
    for flow_id, indices in (fam_stripped.get("_lag_msg_idx_by_flow_id") or {}).items():
        for index in indices:
            owners[index] = flow_id
    return owners


# Normalise one recorded coordinate to a list of plain texts. The stripped side is a flat list of
# strings; the injected side is (tag, text) pairs of which only the `injected` ones are new content
# — the `equal` parts are the surviving original, already on screen as the block body.
def _texts(recorded, side: str) -> list:
    if not isinstance(recorded, list):
        return []
    if side == "stripped":
        return [t for t in recorded if isinstance(t, str) and t]
    out = []
    for span in recorded:
        if isinstance(span, (list, tuple)) and len(span) == 2 and span[0] == "injected" and span[1]:
            out.append(span[1])
        elif isinstance(span, str) and span:
            out.append(span)
    return out
