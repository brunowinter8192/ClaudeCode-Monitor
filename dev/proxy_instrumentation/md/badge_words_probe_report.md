# Badge words probe — strip/inject word badge over recorded dual-logs

| case | request_id prefix | flow_id | expected | actual | pass |
|---|---|---|---|---|---|
| msg84_dot_filler_injection | 0eaf06ba | 508cabc1-7113-45f1-9ce8-44d0616a943e | `strip inject` | `strip inject` | PASS |

  header: `▶ #1 opus 85msg eff:hig think:64k strip inject`

| msg52_bg_wakeup_replacement | 2ae188e7 | d4d32862-ff4a-4d95-8dcf-cc0bdf331079 | `strip inject` | `strip inject` | PASS |

  header: `▶ #1 opus 53msg eff:hig think:64k strip inject`

| strip_only | ca01cd43 | 428318af-dbae-4008-b3f5-36aad3655d32 | `strip` | `strip` | PASS |

  header: `▶ #1 opus 47msg eff:hig think:64k strip`

| neither | daadb2b0 | 5345f334-ef99-4bc8-93b3-ea0aaebd9056 | `(none)` | `(none)` | PASS |

  header: `▶ #1 opus 1msg think:1`

## Overall: ALL PASS