# P3 -- pane-chrome button click probe run (2026-07-30T21:32:54.773541+00:00)

**Result: 24/24 checks passed**

| Check | Result |
|---|---|
| warnings: [refresh] button region registered | PASS |
| warnings: exactly one header region, on row 1 | PASS |
| warnings: button text visible in header | PASS |
| warnings: 'r' key sets _force_refresh | PASS |
| warnings: click on [refresh] sets _force_refresh (same as key) | PASS |
| warnings: width guard -- no region and no button text when pane_width=10 | PASS |
| workers: freeze region registered live | PASS |
| workers: freeze region registered frozen | PASS |
| workers: badge reads [LIVE] when not frozen | PASS |
| workers: badge reads [FROZEN] when frozen | PASS |
| workers: 'f' key toggles frozen False->True | PASS |
| workers: click on freeze badge toggles frozen False->True (same as key) | PASS |
| workers: click on freeze badge toggles frozen True->False | PASS |
| workers: clicking the freeze badge did not select/expand a worker (no collision) | PASS |
| workers: normal row click still selects+expands (milestone-1 undisturbed) | PASS |
| workers: width guard -- no freeze region when pane_width=10 (too narrow) | PASS |
| proxy: [undo] region registered with an empty stack (still clickable) | PASS |
| proxy: [undo] button text visible even with an empty stack | PASS |
| proxy: clicking [undo] with an empty stack is a no-op (same as 'u' key) | PASS |
| proxy: [undo] header text differs empty-vs-non-empty stack (color-coded state) | PASS |
| proxy: clicking [undo] pops the stack and restores prior expand-state | PASS |
| proxy: 'u' key (_undo_proxy_expand) produces the same state change as the click | PASS |
| proxy: body row click (expand/collapse) still works after header/body split | PASS |
| proxy: width guard -- no region and no button text when pane_width=5 (too narrow) | PASS |
