# 2026-08-27 — Exchange content criterion: from "critical for the user" to "concluded this turn"

## Source triage: four of seven indexed sources do not apply

Seven sources were converted and indexed into `monitor-cc-reference` this session to ground a
redesign of the chat-output rules: Chen et al. ("Do NOT Think That Much for 2+3=?"), Singhal
et al. ("A Long Way to Go: Investigating Length Correlations in RLHF"), Xu et al. ("Chain of
Draft"), Sui et al. ("Stop Overthinking", survey), Grice ("Logic and Conversation"), a
practical introduction to the Rational Speech Act framework, and Army Regulation 25-50.

Chen, Chain of Draft, the survey, and the survey's Token Complexity reference all measure
**reasoning tokens** — the tokens a model spends to arrive at a correct answer. Their central
constraint is an accuracy-compression trade-off with a per-task floor ("intrinsic token
complexity") below which correctness breaks.

That constraint does not transfer. In this setup the task is solved in thinking and tool
calls; the chat text is a conversation layer that contributes nothing to solving. There is
therefore no accuracy floor on chat output at all, and the entire efficient-reasoning
literature answers a different question than the one being asked. This was flagged at the
start of the session as a caveat and then repeatedly ignored while arguing from those papers.

Four sources do apply, because they are about an utterance addressed to a listener:

- **Grice** — the maxim of quantity in both directions: as informative as required, and not
  more so. His stated harm from over-informativeness is the useful one here: excess raises
  side issues, and the hearer infers that the excess must have a point.
- **RSA** — formalizes the same trade-off as informativity against utterance cost, and maps
  Quality/Quantity/Manner onto Truth/Informativity/Economy.
- **AR 25-50** — the codified answer-first standard: main point at the beginning ("bottom
  line up front"), understood in a single rapid reading. Its prescribed order is purpose
  sentence, then recommendation or conclusion. It also names ~15 words as the target average
  sentence length, which the existing rule file already matched independently.
- **Singhal** — RLHF gains are largely length gains, and a purely length-based reward
  reproduces most of them. This is the mechanism behind the over-production, and it means the
  tendency is trained in rather than a matter of discipline.

Anthropic's own Opus 5 guidance (also in `monitor-cc-reference`) is consistent: default
visible responses run longer than on prior Opus models, the effort parameter changes thinking
volume rather than visible length, and explicit prompting is the only stated lever.

## The problem, as finally defined

Not repetition. The distinctness measurement in this area found 0.952 corpus-wide, with 99 of
126 turns carrying no redundancy at all.

Not length as such, and not the number of Exchanges in a turn. A turn legitimately spans many
tool calls and worker rounds, and capping it was ruled out throughout.

The problem is **delegation**. Every filter the rules used ("critical information", "process
matter") asked the agent to predict what the user needs. The agent has no access to that, so
it guesses, and it guesses in one direction. Reformulating the same filter in sharper words
changes nothing, because the defect is in who does the judging, not in how the criterion is
phrased.

## The principle that resolved it

**A rule never asks the agent to assess an external party.** The agent can inspect its own
work; it cannot inspect what the user knows, needs, or considers important. Any criterion that
appears to need the user is restated as a question about the agent's own work.

This principle also caught its own violation in the same conversation: a proposed replacement
test ("would you have drawn this sentence from the same source yourself?") was again a
prediction about the user and had to be discarded.

## What was removed from `shared-rules/opus/communication.md`

Three rules, plus two indented sentences:

1. **"An Exchange carries process matter and nothing else."** — its first bullet put "what you
   found" on equal footing with "what you concluded", making every retrieved fact a legitimate
   Exchange. Its definition of process matter was circular.
2. **"An Exchange is only needed for critical information."** — the "critical for the user"
   judgment, i.e. the delegation defect in its purest form. Its escape clause ("if you have to
   ask, it is not") only fires when the agent hesitates, and it does not hesitate.
3. **"Given before new."** — removed entirely. The first bullet required knowing what the user
   already knows. Removing only that bullet left a heading whose "given" no longer referred to
   anything, and two remaining bullets described sentence mechanics that need no rule.
4. Two indented sentences under "The user steers process, and you steer code" that told the
   agent the process domain is what it discusses with the user and that mirroring its own
   process understanding back is part of the job. That pairing is what turned every
   observation about the agent's own work into chat output. The role split itself was kept.

Eight further lines carrying prohibition phrasing were removed or restated earlier in the
session. A count over the file found only three genuine prohibitions among 149 content lines,
so the "the file is mostly prohibitions" reading was wrong: it prescribes structure
thoroughly and prescribes amount not at all.

## What replaced them

```
**An Exchange carries a conclusion you did not hold before this turn.**
- A conclusion is what this turn's thinking and tool calls produced in you.
- Retrieved content is not a conclusion, meaning file content, a search hit, or command output.
- The test is whether the sentence could already have stood in your mind before the turn began.
   - It could have, so it is not an Exchange.
   - It could not have, so it is an Exchange.
- The retrieved facts that carry a conclusion sit in its elaboration.

**The number of Exchanges follows from the conclusions and is never a target.**
- One conclusion means one Exchange, and four conclusions mean four.
- A turn that produced no conclusion carries no Exchange, only its Action frames.
- Nothing caps the count and nothing sets a minimum.
```

The second rule is the reason the first one was acceptable: the Exchange count becomes an
outcome rather than a target, so no cap on turn length is needed anywhere.

## Approaches evaluated and discarded

- **A numeric cap** (max N Exchanges, N bullets, N tool calls per turn). Rejected on the
  grounds that a turn has no natural length. Token Complexity's finding that all prompt-based
  compression strategies land on one accuracy-compression curve — so the number in the
  instruction is the only real lever — was later voided by the source triage above, since that
  curve is about solving, not about the conversation layer.
- **A placement rule** ("everything that could change your decision goes in the bold point").
  Rejected as the same delegation defect wearing a different name: "could change your
  decision" is the same prediction about the user as "critical for the user".
- **A display-layer fix** (render only the bold points, expand elaboration on demand).
  Genuinely non-discretionary, since it makes over-classification harmless rather than asking
  the agent to classify better. Not pursued in this session; it changes the monitor rather
  than the rules and does not reduce what is generated.
- **Cutting "production mandates"** (rules that require output regardless of content, such as
  the closing doubts recap or the hypothesis/fact labelling). Rejected because most of them
  govern content inside an Exchange rather than the number of Exchanges, and the doubts recap
  was judged worth its cost.

## What this does not settle

The conclusion criterion has not been measured against anything. Whether it actually reduces
output, and whether "concluded this turn" proves as elastic in practice as "critical for the
user" did, is open. The one structural advantage claimed for it is that answering it requires
looking at the agent's own turn rather than modelling the reader.
