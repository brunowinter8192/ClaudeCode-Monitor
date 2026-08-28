# Models tab — cycle + I/O verification — 2026-08-28T19:57:00

## 1. Cycle logic
claude-opus-5 -> claude-fable-5
claude-fable-5 -> claude-sonnet-5
claude-sonnet-5 -> claude-opus-5
Third value wraps to first: True
Unrecognized current value starts cycle at first choice: 'claude-opus-5'

## 2. Atomic write
Written file contents: {'main': 'claude-fable-5', 'worker': 'claude-opus-5'}
No leftover .tmp file: True

## 3. Read-back + fallback
Valid file -> ('claude-fable-5', 'claude-opus-5')
Missing file -> ('claude-opus-5', 'claude-sonnet-5') (expected default pair, no raise)
Malformed file -> ('claude-opus-5', 'claude-sonnet-5') (expected default pair, no raise)
Unrecognized-but-valid value file -> ('claude-hand-edited-9000', 'claude-opus-5') (expected preserved verbatim)
Apply without cycling round-trips unchanged -> ('claude-hand-edited-9000', 'claude-opus-5')

RESULT: PASS — cycle order + wrap correct, write is atomic with exact 2-key schema, read-back correct for valid/missing/malformed files, unrecognized values preserved verbatim (not silently replaced).
