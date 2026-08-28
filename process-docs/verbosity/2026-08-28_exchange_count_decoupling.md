# 2026-08-28 — Exchange count decoupled from turn size

## Starting point

The conclusion criterion adopted in this area on 2026-08-27 made an Exchange's *content*
test self-referential ("a conclusion you did not hold before this turn") but left the
*amount* untouched. A re-read of `shared-rules/opus/communication.md` looking specifically
for amount rules found the file contains no upper bound of any kind, and two sentences that
read as explicit permission for unbounded output:

- `A turn has no natural length and no budget.`
- `Nothing caps the count and nothing sets a minimum.`

The working assumption at the start of the session was that both sentences were verbosity
licenses and should be narrowed. That assumption was half wrong, and correcting it is the
substance of this entry.

## The actual defect: turn size read as output size

A turn is a unit of *work*, bounded by the idle→working→idle transition. Its length is how
much work happens before going idle: tool calls, thinking, worker dispatches. The "no budget"
sentence licenses that work — it exists to prevent going idle prematurely after five tool
calls. It says nothing about how much text gets written.

The agent had been reading it as an output license, and more generally had been scaling
written output with work performed: a forty-tool-call turn *felt* like it owed a large
report. Nothing in the rule file couples the two. The coupling was entirely the agent's.

One sub-bullet did reinforce it: `A turn running dozens of tool calls and many Exchanges is
a normal turn` names high tool-call count and high Exchange count in one breath as the same
normality.

## External research

### The field (Reddit, r/ClaudeCode + r/ClaudeAI + r/PromptEngineering + r/claudeskills)

Five index runs over verbosity-control posts. What people actually do, weakest to strongest:
`CLAUDE.md` instructions → output styles (modify the system prompt) → `--system-prompt-file`
(actually replaces the conciseness block) → hooks (`UserPromptSubmit` re-injection each turn,
or a `Stop` hook that word-counts the finished reply and bounces it with `exit 2`).

The single measured data point in the corpus is a **negative** result. One user counted every
assistant reply in their local `~/.claude/projects/**/*.jsonl` (prose characters only, tool
calls excluded): no output style — 2,951 replies, median 133 chars, 12.4% ≥1000 chars; their
own anti-verbosity style — 459 replies, 31.8% ≥1000 chars; a rewritten v2 — 94 replies, 12.8%.
Their verbosity rules nearly **tripled** the share of long replies against no rules at all.
The v2 gain against baseline is roughly 10% and comes from fewer long replies, not shorter
ones; n=94 over two days is thin and the author says so.

Two causes named for the v1 failure, both directly applicable here:
1. **Example blocks get copied as templates rather than followed as rules.** They were ~40%
   of their v1 and were deleted entirely in v2.
2. **Hedged wording** (`prefer`, `avoid`, `when useful`) is guesswork, not steering.

### Anthropic's own position

A source-code analysis post on the `USER_TYPE === 'ant'` build flag reports that Claude Code
ships two different output-style sections from one source tree. External build:
`Be extra concise`, `Lead with the answer or action, not the reasoning`, `If you can say it
in one sentence, don't use three`. Internal build: that section is replaced wholesale, the
`short and concise` tone line is nulled, and it reads `Err on the side of more explanation`
and `What's most important is the reader understanding your output without mental overhead
or follow-ups, not how terse you are`. The internal build *also* carries hard anchors:
`≤25 words between tool calls`, `≤100 words for final responses unless the task requires
more`. Not independently verified here; treated as a claim about that binary.

Anthropic's published prompting guidance for the current model agrees on mechanism: output is
shortened by **selection**, not by compressing the writing into fragments, abbreviations, or
arrow chains, and "being readable and being concise are different things".

The internal build also explicitly asks for `Before your first tool call, briefly state what
you're about to do` — which is what Action frames already do. That settled a candidate cut:
Action frames were left alone.

## The principle that held: no rule may require modelling the user

The field's standard filter is a utility test — Anthropic's own guidance phrases it as
`drop details that don't change what the reader would do next`, and the most-copied Reddit
`CLAUDE.md` as `If a detail does not change my understanding, decision, or next action, leave
it out`. It was proposed in this session and **rejected**, for the same reason the 2026-08-27
entry rejected "critical for the user": the agent has no access to what the reader needs, so
it guesses.

The asymmetry of failure modes is the concrete argument. A utility test fails **silently** —
what it drops is never shown, so the user cannot detect the loss. A novelty test fails
**loudly** — it lets too much through, which the user can see and dismiss. Over-inclusion is
recoverable; silent omission is not.

The novelty test is therefore not a compromise but the better instrument, and it appears to
have no precedent in the field: no Reddit setup and no Anthropic guidance uses it.

## Why the novelty test still does not bound the count

Novelty is abundant. Every file read produces conclusions the agent did not previously hold,
and the rule excludes retrieved content but not conclusions *about* retrieved content, of
which there is an unlimited supply. An absolute test has no scarcity in it.

Two candidate sources of scarcity were worked through:

- **A relative test** (rank this turn's conclusions against each other, only the top N get an
  Exchange). Self-checkable, no user modelling. Not adopted — superseded by the next point.
- **A layer test**, contributed by the user as a worked example. Asked the colour of a house
  and why: L1 "it is green" (observation), L2 "moss, or paint?" (hypotheses), L3 "painted, with
  some plants" (refined observation), L4 "green, and the cause is multicausal" (resolution).
  Only L4 is a conclusion. L1–L3 are the path, and L4 already contains them in compressed
  form — which is exactly what the existing point/elaboration split is for. The agent had been
  emitting L1, L2 and L3 each as its own bold point.

Retro-applied to this session's own Reddit turn: 7 Exchanges, of which the technique
inventory sat at L1 and the template-cause finding at L4, both rendered in identical
formatting. The user sees raw observation and finished result in the same wrapper.

## Introspection: threads, not strands, and no end signal

The user asked directly whether reasoning runs as strands (start → 1 → 2 → 3, with a detectable
end) or interleaved. Reported honestly: interleaved. During the Reddit read, at least four
threads advanced in fragments side by side — techniques, transferability, an older hypothesis,
German phrasing. The linearity of a thinking block is the output channel, not the process.
Whether the parallelism is real or reconstructed after the fact is not introspectable.

More consequentially: **there is no completion signal.** Writing stops when "therefore" becomes
more natural than "and also" — a fluency effect, not a completeness check. So what gets reported
is where a thread currently *stands*, not where it *ends*, which is the mechanism behind emitting
L1 material as if it were L4.

A weak end-detector was identified (a thread is finished when advancing it produces no new
question) but it only discriminates when paired with a real originating question — a listing
that was never a question also produces no follow-up. Not written into the rules.

The same probe surfaced that the turn-closing decision-required Exchange was frequently
manufactured: of the session's turns, most closed on a 🛑 that asked for approval rather than
naming a genuine blocker. The user rejected this as off-topic — the subject was the number of
Exchanges, not the closing gate — and it was dropped without a rule change.

## What changed in `shared-rules/opus/communication.md`

Under `YOU decide how long a turn is`:

```
- A turn has no natural length and no budget.
   - The absent budget covers the work, never the text you write.
   - A turn running dozens of tool calls is a normal turn.
```

The `and many Exchanges` clause was removed from the sub-bullet — it was the one line in the
file that named tool-call volume and Exchange volume as the same normality.

Added as its own bold point directly after `The number of Exchanges follows from the
conclusions and is never a target`:

```
**The Exchange count is decoupled from everything else the turn contained.**
- The number of tool calls, the amount of thinking, and the number of Action frames do not move the Exchange count.
   - Forty tool calls and one tool call both yield one Exchange when both produced one conclusion.
- A long turn owes no long report, so the report tracks the conclusions and nothing else.
```

Placed as a sibling rather than as bullets under the existing point, because the existing point
says where the number comes from (conclusions) and the new one says where it does not come from
(effort) — two statements, and the second disappears if nested.

Two drafting corrections, both from rules already in force: the point first read `The count is
decoupled…`, which only resolves via its neighbour and violates the unambiguous-naming rule; and
a bullet reading `Effort spent is never a reason to write more, because the effort is not what the
user reads` was cut on the user's call.

## Approaches evaluated and discarded

- **A cap on elaboration bullets per Exchange** (proposed at 3). Discarded: the user's complaint
  was the number of Exchange paragraphs, not bullets within one.
- **Deleting the `Style for Exchanges` example block**, on the Reddit finding that example blocks
  are copied as templates. Discarded: the block is the only thing conveying *form*, and for form
  a template is exactly what is wanted. The template-copying effect is real but it applies to the
  block's *quantity*, not its shape — a separate problem, left open.
- **A hard numeric cap on Exchanges per turn** (proposed at 3, then 2). Not adopted: the decoupling
  rule addresses the cause, so a cap was judged unnecessary rather than wrong.
- **The utility test**, in both the Reddit and the Anthropic phrasing. Rejected on the delegation
  principle (see above).
- **Hook-based enforcement** — a `Stop` hook that word-counts and bounces, or a `UserPromptSubmit`
  hook re-injecting the rule each turn. Deterministic where a rule depends on compliance, and the
  strongest lever the field has. Rejected by the user for this system.
- **Output styles / `--system-prompt-file`**. Not applicable: `communication.md` is already injected
  into the system prompt by the proxy, i.e. already at the strongest instruction position. The whole
  Reddit ladder was moot for this setup.

## What this does not settle

Nothing was measured. Whether the decoupling rule changes the Exchange count is unknown; the
distinctness corpus in this area predates it and would have to be re-run against post-change turns
to say anything. The layer-1-to-4 definition of a conclusion was agreed in conversation but is
**not written into the rule file** — only the decoupling is. Whether the existing conclusion test
plus the decoupling is enough to make the agent emit L4 rather than L1, or whether the layer
distinction needs its own rule, is open.

The `Style for Exchanges` block still shows three to four bullets per Exchange, and the Reddit
finding that such blocks are copied as templates was accepted as plausible without being tested
here.
