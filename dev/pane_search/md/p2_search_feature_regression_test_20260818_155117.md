# P2 search feature regression — 20260818_155117

26/26 checks passed

- [x] empty query: 'search: _' pattern present
- [x] populated query: query text 'foo' visible in row 1
- [x] row 1 has no line_map entry
- [x] every line_map row is >= 2
- [x] all 5 REQ headers present in shifted line_map
- [x] exactly entry 2 matches 'unique_marker_2'
- [x] exactly one line carries SEARCH_CURRENT_BG (the collapsed REQ header)
- [x] 2 lines carry SEARCH_CURRENT_BG (header + inner content line)
- [x] the inner marked line actually contains the matched text
- [x] n: 0 -> 1
- [x] n: 1 -> 2
- [x] n wraps: 2 -> 0
- [x] N wraps backward: 0 -> 2
- [x] n/N no-op with zero matches
- [x] cancel returns True (always redraws)
- [x] query cleared
- [x] focused cleared
- [x] matches cleared
- [x] bar still rendered at row 1 after Esc (permanent, not hidden)
- [x] _proxy_just_expanded set to the match's req key
- [x] post-jump scroll_offset is non-negative
- [x] the jumped-to entry is present in the rendered line_map
- [x] scroll_offset stable across a second render (clamp is idempotent)
- [x] batch2 has 2 entries (flow-C, flow-D)
- [x] batch2's _fwd_req_idx COLLIDES with batch1's (0,1) — confirms the bug scenario applies
- [x] every batch2 entry lazy-loads its OWN content (flow_id-correct, not index-collided)
