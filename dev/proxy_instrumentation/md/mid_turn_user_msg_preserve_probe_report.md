# Mid-turn user message preserve-guard probe (issue #61, CC 2.1.223)

Preserve case session: `api_requests_opus_posts_1786051932`. Regression-noise session: `api_requests_opus_websearch_1786052022`.

| case | pass | detail |
|---|---|---|
| msg274_mid_turn_user_msg_preserved | PASS | role='system', content_len=287, 'jetzt' present=True, untouched=True, changed_idxs contains 274=False |
| deferred_tools_still_stripped | PASS | orig_prefix_match=True, result='.', changed_idxs contains 1=True |
| task_tools_nag_still_stripped | PASS | orig_prefix_match=True, result='.', changed_idxs contains 33=True |
| date_changed_still_stripped | PASS | orig_prefix_match=True, result='.', changed_idxs contains 49=True |

## Overall: ALL PASS