# 2026-07-30 — CotEditor Space-jump: investigation dropped, shift-click replaces drag-selection

## Status at close

The Space jump was never reproduced under instrumentation. The menubar app had been ruled out as
the trigger by live repro; the remaining hypothesis — a Mission Control edge-drag Space switch
firing when the drag-selection cursor reaches the screen edge — stayed unproven. A 10 Hz logging
probe was armed to capture the next real jump; no jump was captured before the investigation was
dropped.

## Why it was dropped: the workaround is strictly better than the fixed behaviour

Selecting via click-at-line-start → hover-to-line-end → shift-click never jumps. The user reports
it is also FASTER than holding the button and dragging. So the workaround is not a degraded
substitute accepted under duress — it dominates the original interaction on both correctness and
speed. Fixing drag-selection would restore an interaction nobody would go back to.

That the shift-click path is jump-free is also the strongest evidence on file for the trigger being
drag-specific (button held down while the pointer moves), not selection-related — consistent with
the edge-drag hypothesis, though still not proof, since no instrumented jump was ever captured.
