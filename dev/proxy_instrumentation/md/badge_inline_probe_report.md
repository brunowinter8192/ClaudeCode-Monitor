# Badge-inline probe — per-flow span visibility + neighbor-bleed fix

Session: `api_requests_opus_websearch_1786052022` (62 forwarded entries)

| case | flow_id | pass | detail |
|---|---|---|---|
| msg1_deferred_tools_notice_below_window | fa0ba243-86b1-47ef-aa32-fa9a9a384c38 | PASS | badge='strip inject' (want 'strip inject'), [1] present=True, olive=True, green=True |
| msg33_task_tools_nag_outside_window_core_case | 9f02e2cd-209d-45a8-b98b-d06fcaf117c9 | PASS | badge='strip inject' (want 'strip inject'), [33] present=True, olive=True, green=True |
| msg38_bg_notification | 9f75f100-0d05-480a-bf4d-53f2de78e149 | PASS | badge='strip inject' (want 'strip inject'), [38] present=True, olive=True, green=True |
| empty_delta_no_bleed | 01e683fe-e00a-498e-8cd0-2dbe6ff4bca7 | PASS | badge='' (want none), spans_in_own_body=False, foreign_lookup(msg=1)=False |
| synthetic_fields_only_no_badge | synthetic_fields_only | PASS | has_content=False (want False), fields_kept=True (want True) |
| no_warn_s_badge | (all) | PASS | ⚠S in rendered output=False (want False), ⚠T in render_turn.py source=True (want True), ⚠S in render_turn.py source=False (want False) |

## Overall: ALL PASS