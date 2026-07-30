# P1 -- worker-selection click probe run (2026-07-30T20:12:10.664139+00:00)

**Result: 22/22 checks passed**

| Check | Result |
|---|---|
| worker-proxy: one header region per worker | PASS |
| worker-proxy: region targets match worker names | PASS |
| worker-proxy: region coordinates plausible (1-based, sc<=ec, er>=1) | PASS |
| worker-proxy: header regions do not overlap | PASS |
| worker-proxy: digit-key '1' selects 'alice' | PASS |
| worker-proxy: click at col 18 row 1 on '[1]alice' selects it | PASS |
| worker-proxy: click/key parity for 'alice' | PASS |
| worker-proxy: digit-key '2' selects 'bob' | PASS |
| worker-proxy: click at col 27 row 1 on '[2]bob' selects it | PASS |
| worker-proxy: click/key parity for 'bob' | PASS |
| worker-proxy: digit-key '3' selects 'carol' | PASS |
| worker-proxy: click at col 36 row 1 on '[3]carol' selects it | PASS |
| worker-proxy: click/key parity for 'carol' | PASS |
| workers-pane: one header-row region per worker | PASS |
| workers-pane: header-row coordinates plausible (row>=1) | PASS |
| workers-pane: digit-key '1' expands+selects 'w1' | PASS |
| workers-pane: click on row 3 ('w1') produces same expand+select | PASS |
| workers-pane: click/key parity for 'w1' | PASS |
| workers-pane: digit-key '2' expands+selects 'w2' | PASS |
| workers-pane: click on row 6 ('w2') produces same expand+select | PASS |
| workers-pane: click/key parity for 'w2' | PASS |
| workers-pane: scroll wheel on a worker row still handled (no collision) | PASS |
