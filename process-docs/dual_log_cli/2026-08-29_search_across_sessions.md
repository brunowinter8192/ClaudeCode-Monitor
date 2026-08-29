# 2026-08-29 — Search grows a scope, and the argument order flips

Seventh entry of this area. `search` was single-session by construction: `search <session> <term>`
resolved one stem and searched it. That answers "where in this session did X happen" but not "where
did X happen at all", which is the question a log corpus exists for. The command now scopes like
`sessions` does.

## New shape

```
search <term> [scope] [--since D] [--until D] [--case-sensitive]
```

- **term first**, deliberately breaking the old order.
- **scope** optional, case-insensitive, matched against the session's **context OR stem** — so
  `websearch` covers a project including its workers, and `gh_cli_1787995963` still drills a single
  session. One argument, both granularities.
- date flags identical to `sessions`; no scope and no dates searches everything.

Output: the term line once at the top, then per matching session a `session <stem>` line and its
hit lines, blank-line separated. Sessions without hits are omitted entirely, zero hits overall
prints `no match`, and a trailing note names how many sessions were skipped — only when the count
is non-zero, so a clean run stays clean.

## Selector split: scope vs context

`filter_sessions` now carries two optional substring selectors. `context` matches the rendered
context only and belongs to `sessions`; `scope` matches context OR stem and belongs to `search`.
Both AND with the date window. Keeping them as separate parameters rather than widening `context`
was deliberate: `sessions` is a browsing command where matching a stem substring would blur the
context column's meaning, while `search` wants the stem as a legitimate target because a session id
is exactly how one drills into a single conversation.

## The breaking change fails silently, and that is worth knowing

An old-style call — `search gh_cli_1787939513 milestone` — is still structurally valid: the stem
becomes the term, the term becomes the scope. It does not error. It prints:

```
term      "gh_cli_1787939513"  (case-insensitive)

no match
```

with exit 0. Nothing warns. A guess-based guard (treat a leading argument that looks like a stem as
the session) was considered and rejected: it would make the signature ambiguous forever, and a
literal stem is a perfectly reasonable thing to search FOR. The silent failure is documented as a
package gotcha instead, since every caller has to be moved deliberately.

## Cost

Unscoped search over the whole corpus: **1.42 s** for 61 sessions (3 runs: 1.44 / 1.42 / 1.42).
A rare term measured identically, which places the entire cost in the per-session reconstruction
rather than in the matching — scope and date flags are the only speed levers, and they work by
reconstructing fewer sessions, not by searching faster.

For comparison, the inventory that selects those sessions costs 0.27 s and reads only `_forwarded`;
the extra ~1.15 s is 61 reverse-seeks plus 61 JSON parses of a last request.

## Skipping is per session, not fatal

One truncated log must not hide the matches in the other sixty, so `load_timeline` failures are
counted and skipped. No real session triggers this, so it was verified against a synthetic fixture:
an empty `_original` beside a valid `_forwarded` (which is what makes the session appear in the
inventory at all). With a healthy session alongside it, the run reports the healthy hit and ends
with `(1 session skipped — timeline could not be loaded)`; with no hits anywhere it prints
`no match` and still shows the note.

## Verification

- `search "Reißleine" websearch --since 2026-08-28 --until 2026-08-28` → 16 hits across the two
  opus websearch sessions. The scope also selected that day's `hookfix` and `discovery` workers;
  neither contained the term, and both are absent from the output.
  Two of the hits match lowercase `reißleine`, confirming case-insensitivity on a non-ASCII term.
- Single-session drill unchanged: `search "worker-cli merge" gh_cli_1787939513` → the same 2 hits
  as before the redesign.
- Scope resolves case-insensitively against either target: `DISCOVERY` (uppercase, context) → 1
  session; `1787939513` (stem digits only) → 1 session.
- `--since nope` → exit 2; empty term → exit 2; date-scoped miss → `no match`.
- Regressions: `sessions` 61, `sessions websearch --since/--until` 4, `timeline` header unchanged,
  piped output 0 bytes on stderr.

## An observation from the run

The corpus now contains this work's own sessions, so a probe term used in an earlier milestone
(`zzz_no_such_term_zzz`, chosen because nothing could match it) is found in several sessions — the
transcripts of the tests that used it. Search over a live log corpus includes the searching itself.
