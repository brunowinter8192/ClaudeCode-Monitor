# Flow-extra suppression probe — total_tokens nuke no longer prepends

Each session is rendered twice in one process: once with the parser's
substantial-index lookups attached (current behavior) and once without them
(baseline = pre-suppression fallback path). Diffs are the suppression only.

## `api_requests_opus_monitor_cc_1788091735`

| metric | value |
|---|---|
| entries_rendered | 73 |
| entries_prepending_before | 64 |
| entries_prepending_after | 10 |
| indices_suppressed | 55 |
| indices_kept | 10 |

| check | pass | detail |
|---|---|---|
| suppressed_blocks_dropped_exactly | PASS | 55 entries drop an insubstantial prepend (54 of them lose it entirely, the rest are mixed and keep their real one); dropped prefix matches the suppressed indices and the tail is verbatim; bad=[] |
| substantial_only_identical | PASS | 9 entries prepend only substantial indices; byte-identical to baseline; bad=[] |
| no_flow_extra_identical | PASS | 0 entries never prepended; byte-identical to baseline; bad=[] |
| badges_unchanged | PASS | 73 entries compared via parser.badge_flags; changed=[] |
| split_matches_parser_verdict | PASS | 55 suppressed / 10 kept indices cross-checked against _msg_delta_entry_is_substantial; bad=[] |

## `api_requests_opus_gh_cli_1787995963`

| metric | value |
|---|---|
| entries_rendered | 487 |
| entries_prepending_before | 449 |
| entries_prepending_after | 67 |
| indices_suppressed | 384 |
| indices_kept | 67 |

| check | pass | detail |
|---|---|---|
| suppressed_blocks_dropped_exactly | PASS | 384 entries drop an insubstantial prepend (382 of them lose it entirely, the rest are mixed and keep their real one); dropped prefix matches the suppressed indices and the tail is verbatim; bad=[] |
| substantial_only_identical | PASS | 65 entries prepend only substantial indices; byte-identical to baseline; bad=[] |
| no_flow_extra_identical | PASS | 0 entries never prepended; byte-identical to baseline; bad=[] |
| badges_unchanged | PASS | 487 entries compared via parser.badge_flags; changed=[] |
| split_matches_parser_verdict | PASS | 384 suppressed / 67 kept indices cross-checked against _msg_delta_entry_is_substantial; bad=[] |

## Overall: ALL PASS
