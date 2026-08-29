# 2026-08-29 — Dropping the request markers from the expand overview

Ninth entry of this area, and a small one: the `expand` overview no longer interleaves the
`── REQ n ──` boundary lines it inherited from `timeline`. Nothing else changed — same window, same
classifier lines, same `▶` anchor mark, and `timeline` keeps its markers untouched.

## Why they were there, and why they left

`expand`'s overview was built by reusing the timeline renderer's shape, markers included. That was
the cheap thing to do and it looked right in isolation. In use it is not: the two views answer
different questions.

`timeline` is a request-shaped view — the markers ARE its structure, they show which turns arrived
in which API call and where the conversation grew. `expand` is a turn-index view: the caller
arrives with an index from `search`, wants the neighbourhood of that index, and reads down a
continuous run of numbers. Interleaving a second, unrelated numbering into that run makes the
reader track two counters at once for no gain — the request number is never what they came for.

Measured on the same anchor: 61 classifier lines with 20-odd marker lines cutting through them
before, 61 uninterrupted lines after.

## What this is an instance of

The same judgement as the `sessions` column trim and the `search` header trim recorded in this
area: output that is cheap to produce and locally sensible still earns its place only by answering
the question the command exists for. Three trims in this area now, all in the same direction, none
of them removing information that the other views do not still carry — the request view lives in
`timeline`, in full, unchanged.

## Verification

- `expand websearch_1787924727 713` → 0 REQ lines, 61 classifier lines, window `683-743` unchanged.
- `timeline websearch_1787924727` → 265 REQ lines, unchanged.
- `expand --full` untouched; `boundaries_by_index` still imported and used by `render_timeline`,
  so nothing became dead code; piped output still 0 bytes on stderr.
