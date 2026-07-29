# Live observations of the proxy-side background messages, 2026-07-29

Orchestrator-side live session against a RUNNING proxy carrying the 2026-07-28/29 merged state
(the frozen source copy in place before this session's own fixes). Everything below was observed
by being the RECEIVING model — the forwarded content as it actually arrived, not read out of a log
or inferred from code. Recorded here because a running proxy is the only source for these
observations and the measurement/fix milestones of the same day could not produce them.

## Method

Ran a sentinel-controlled Bash counting loop (`while [ ! -f /tmp/stop-bg-loop ]`), had the user
manually background it mid-run, then terminated it by touching the sentinel — so both the launch
and the termination message were produced by a real CC background task, twice, once per launch
path. Separately started `sleep 600 && echo done` with `run_in_background=true` for the
agent-initiated path, and read a process-docs file containing a line-anchored, markdown-fenced
`<system-reminder>` example block through the Read tool for the quoted-SR question.

## Termination message — correct on BOTH launch paths

The wake-up arrived as the canonical 3 lines in both cases (agent-backgrounded and
user-backgrounded): the wake-up sentence, `Output: <path>`, `ID: <task id>`. No bare `'.'`,
nothing truncated. The two ids observed were `bsxpatpam` (user-backgrounded loop) and `bcexi2n0t`
(agent-started timer). This closes the previously-unverified `role='system'` plain-str delivery
question: the reworked path is not nuked on a live proxy.

## Launch acknowledgement — correct only on the agent-initiated path

Agent-initiated (`run_in_background=true`): the replacement fired, 3 lines, own `ID:` line.

User-manually-backgrounded: the replacement did NOT fire. What arrived was CC's unmodified original
text, with the id embedded mid-sentence and no separate `ID:` line:

```
Command was manually backgrounded by user with ID: bsxpatpam. Output is being written to: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/587284d6-c174-4432-a8d0-b5e2bcf10f0b/tasks/bsxpatpam.output
```

Cross-checked two independent ways: the text is exactly 220 characters, matching the block size the
proxy pane reported for that block (`220c`), so the ack is complete and genuinely ends after the
path — there is no trailing `. You will be notified when it completes…` sentence on this path.
`grep` for `manually backgrounded` across `src/proxy` returned 0 hits: this launch path was never
implemented, rather than implemented and broken.

## There is no third launch path — CC kills instead of backgrounding on timeout

Tested directly: a 400-second Bash loop with no `run_in_background` and no timeout override. CC did
NOT background it on hitting the limit — the call was killed at the 2-minute boundary
(`Command timed out after 2m 0s`, exit code 143), with the loop's own log confirming it stopped at
tick 120. So the launch-wording space is 2 wordings, not 3.

One loose end, unresolved: a third task output file (`b7gjft8ks.output`) appeared in the task
directory at the moment of that kill and was gone seconds later when read. CC evidently allocates
a task id before aborting; whether that ever produces a forwarded message could not be determined
from the receiving side.

## Quoted `<system-reminder>` block survives the strip passes

Read `process-docs/proxy_noise_strip/task_2026-05-30.md`, which embeds a verbatim, real-newline,
markdown-fenced env-context `<system-reminder>` block — line-anchored, i.e. exactly the shape the
SR strip passes used to remove out of quoted tool output. All 9 lines of the block arrived intact,
including the address and date inside it. The 2026-07-28 change stopping the SR strip family from
descending into `tool_result` holds on a live proxy.

## Pane rendering of the replaced launch ack — split across two lines

User-observed in the proxy pane (screenshots reviewed in-session): the replaced agent-initiated
launch ack rendered with the shared leading word `Command` unhighlighted on its own line, the
replacement text green on the lines below. The termination message rendered as one contiguous green
block — consistent with it sharing no leading word with the text it replaced.

## Verification boundary as of this session

The observations above describe the proxy state BEFORE this session's own fixes; the running proxy
uses a frozen source copy and only picks up source changes on restart. Consequently NOT verified
live: the second launch wording being recognized, and the replaced ack rendering as one contiguous
green span. Both were verified only at integration level (real corpus + real production functions)
in the same day's fix milestones. The live gate needs a proxy restart, then re-running exactly the
two launch paths above.

## Sources for CC's own message wordings

CC's launch/termination message texts are not documented anywhere externally — CC emits them, and
no vendor documentation covers them. The only two sources are the project's own recorded dual-log
corpus (`src/logs/dual_log/`) and a strings dump of the CC binary itself. The corpus answered the
wording question this session, so the binary dump was named as an option and not used; it remains
the route to enumerate all variants at once should a third wording ever be suspected.
