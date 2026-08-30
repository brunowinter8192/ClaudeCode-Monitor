# No-prepend probe — the expanded body is the request payload delta only

The out-of-window flow-extra prepend was removed on 2026-08-30. These invariants
are self-contained: there is no pre-change rendering left to diff against, and
counts are reported rather than asserted so log growth cannot break them.

## `api_requests_opus_monitor_cc_1788091735`

| metric | value |
|---|---|
| entries_rendered | 148 |
| entries_with_out_of_window_touch | 129 |
| entries_whose_out_of_window_touch_is_substantial | 23 |
| out_of_window_indices_now_invisible | 132 |
| entries_showing_in_window_spans | 37 |

| check | pass | detail |
|---|---|---|
| no_msg_below_delta_window | PASS | 148 entries rendered; bodies starting below their own delta window: 0 [] |
| removed_symbols_stay_removed | PASS | render_messages still exporting none; parser mentions _msg_idx_sub_by_flow_id: False; entries carrying a sub-lookup: 0 |
| substantial_out_of_window_strips_still_badge | PASS | 129 entries have an out-of-window touched index, 23 of them SUBSTANTIAL; of those 0 show NO badge word (want 0) [] |
| in_window_spans_still_render | PASS | 37 of 148 entries render an olive/green span in-window |

## `api_requests_opus_gh_cli_1787995963`

| metric | value |
|---|---|
| entries_rendered | 487 |
| entries_with_out_of_window_touch | 449 |
| entries_whose_out_of_window_touch_is_substantial | 67 |
| out_of_window_indices_now_invisible | 451 |
| entries_showing_in_window_spans | 73 |

| check | pass | detail |
|---|---|---|
| no_msg_below_delta_window | PASS | 487 entries rendered; bodies starting below their own delta window: 0 [] |
| removed_symbols_stay_removed | PASS | render_messages still exporting none; parser mentions _msg_idx_sub_by_flow_id: False; entries carrying a sub-lookup: 0 |
| substantial_out_of_window_strips_still_badge | PASS | 449 entries have an out-of-window touched index, 67 of them SUBSTANTIAL; of those 0 show NO badge word (want 0) [] |
| in_window_spans_still_render | PASS | 73 of 487 entries render an olive/green span in-window |

## Overall: ALL PASS
