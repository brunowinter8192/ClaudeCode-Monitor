# queue_delay_ms Metric Validity — Contradiction and Hypothesis (2026-08-19)

Orchestrator-side analysis from the session chat; complements the M2/M3 entries in this area.
The `queue_delay_ms` instrumentation (Carbon `GetEventTime` vs handler-entry
`GetCurrentEventTime`, `hotkey_controller.py`) is most likely BLIND to pre-dispatch queuing —
do not treat its near-zero values as proof that hotkey handling was fast.

## The contradiction (measured, same log window)

As of 2026-08-19, in the window 18:14-18:15 (pre-M3 build): main-thread ticks of 3.9-4.6s ran
every ~10s (desktop_detection-driven, post-TCC-regrant), i.e. the main thread was blocked ~40%
of wall time — while 63 real user presses in the SAME window logged queue_delay_ms of
0.1-1.0ms (median 0.2). Both cannot be true if `GetEventTime` reflected the physical
key-press time: presses landing inside a 4s stall would have to show multi-second deltas, and
with that many presses several statistically must have landed inside stalls.

## Hypothesis (unproven, consistent with all observations)

Carbon sets the hotkey event's `EventTime` at event CREATION/DISPATCH — which for a global
hotkey happens when the runloop is ready to process it — not at hardware key-press time. The
delta then measures only handler dispatch overhead (~0.2ms always) and is structurally blind
to the very stall it was designed to catch.

## Consequence

- The M3 fix (discovery off the main thread) did not depend on this metric; the tick-phase
  measurements alone identified and proved the blocker, and the user confirmed the perceived
  latency fix live.
- Anyone reading `[latency] hotkey=... queue_delay_ms=...` lines later: near-zero values do
  NOT certify a responsive main thread. If a press-to-effect latency proof is ever needed,
  measure at a different layer (e.g. a CGEventTap timestamp on the keydown, or
  press-to-visible-UI timing) — the Carbon event timestamp is not that layer.
