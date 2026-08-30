# No-prepend probe — the expanded body is the request payload delta only

The out-of-window flow-extra prepend was removed on 2026-08-30. These invariants
are self-contained: there is no pre-change rendering left to diff against, and
counts are reported rather than asserted so log growth cannot break them.

## `api_requests_opus_monitor_cc_1788091735`

| metric | value |
|---|---|
| entries_rendered | 191 |
| entries_with_out_of_window_touch | 166 |
| entries_whose_out_of_window_touch_is_substantial | 28 |
| out_of_window_indices_now_invisible | 169 |
| entries_showing_in_window_spans | 165 |
| lag_corrected_coordinates | 140 |

| check | pass | detail |
|---|---|---|
| no_msg_below_delta_window | PASS | 191 entries rendered; bodies starting below their own delta window: 0 [] |
| removed_symbols_stay_removed | PASS | render_messages still exporting none; parser mentions _msg_idx_sub_by_flow_id: False; entries carrying a sub-lookup: 0 |
| substantial_out_of_window_strips_still_badge | PASS | 166 entries have an out-of-window touched index, 28 of them SUBSTANTIAL; of those 0 show NO badge word (want 0) [] |
| in_window_spans_still_render | PASS | 165 of 191 entries render an olive/green span in-window |
| lag_correction_sound_and_effective | PASS | 140 coordinates re-attributed to the flow that stripped them; 0 carry non-marker text (want 0) []; 0 sit in-window without olive+green (want 0) [] |

## `api_requests_opus_gh_cli_1787995963`

| metric | value |
|---|---|
| entries_rendered | 487 |
| entries_with_out_of_window_touch | 449 |
| entries_whose_out_of_window_touch_is_substantial | 67 |
| out_of_window_indices_now_invisible | 451 |
| entries_showing_in_window_spans | 425 |
| lag_corrected_coordinates | 384 |

| check | pass | detail |
|---|---|---|
| no_msg_below_delta_window | PASS | 487 entries rendered; bodies starting below their own delta window: 0 [] |
| removed_symbols_stay_removed | PASS | render_messages still exporting none; parser mentions _msg_idx_sub_by_flow_id: False; entries carrying a sub-lookup: 0 |
| substantial_out_of_window_strips_still_badge | PASS | 449 entries have an out-of-window touched index, 67 of them SUBSTANTIAL; of those 0 show NO badge word (want 0) [] |
| in_window_spans_still_render | PASS | 425 of 487 entries render an olive/green span in-window |
| lag_correction_sound_and_effective | PASS | 384 coordinates re-attributed to the flow that stripped them; 0 carry non-marker text (want 0) []; 0 sit in-window without olive+green (want 0) [] |

## Overall: ALL PASS
