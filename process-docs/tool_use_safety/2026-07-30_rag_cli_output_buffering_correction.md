# 2026-07-30 — Correction: rag-cli output is block-buffered, not incremental

## What was assumed

Earlier the same day, an auto-backgrounded `rag-cli index` run was observed holding four open write
handles on its `<tasks>/<id>.output` file while the file itself was 0 bytes. The reading taken from that
was: the file is empty because nothing has flushed YET, and a `rag-cli index` run writes its
`Indexed N/M chunks` progress continuously — so any size-based liveness check would go stale within
seconds of the run starting.

## What the measurement showed

The first half holds, the second does not. Two full real `rag-cli index` runs of the 547 KB
`BreimanFriedmanOlshenStone1984CART.md` document (382 chunks, ~9-10 min end-to-end against a warm local
`llama-server`) kept the tracked `.output` file at **0 bytes for the entire run**, then jumped to the
complete 457-byte log in one flush at process exit.

Cause read from source: `rag-cli`'s progress printer at `src/rag/indexer.py:122` (`_embed_store_batches`)
does `print(f"Indexed {chunks_done}/{total} chunks{suffix}")` with no `flush=True`, and no module
reconfigures stdout to line-buffering. Redirected to a file, stdout is fully block-buffered — the run
produces no visible output at all until it ends.

Prefixing the run with `PYTHONUNBUFFERED=1` produced genuine incremental writes (file at 175 bytes / 3 of
12 progress lines while the process was still ~6-7 minutes from completion). That forced run is what
demonstrated the size-predicate failure against a REAL workload.

## Why the conclusion still stands

The claim "file size is not a liveness signal, an open write handle is" is unaffected — it just rests on
different evidence than assumed:

- a buffered writer sits at 0 bytes for its whole runtime → size says "maybe running" only by accident
- an unbuffered writer passes 0 bytes within seconds → size says "finished" while it runs
- a synthetic writer loop measured at 18 bytes after 3 s while still running → same failure, no rag-cli
  involved
- in every one of those states the open handle is present, and it disappears exactly at process exit

So size is wrong in both directions depending on buffering, which is a property of the child process and
not observable from outside. The handle is not.

## Second confound worth recording

The mirror-image failure also showed up in real data: a session's tasks dir carrying a stale 0-byte
`*.output` file left behind by a prior no-output task makes a size-based predicate report "busy" forever,
until someone deletes the file by hand. Handle-based reports it correctly as idle.

## Probe methodology note

A long-lived measurement process run INSIDE the very CC session it measures becomes itself an open handle
in that session's tasks dir — the session then reads as permanently busy and the probe can never observe
its own "after" state. One such probe sat waiting 14 minutes for a condition it was itself preventing.
Short, individually-fast checks driven from outside avoid this. The real menubar process lives outside
every session it monitors and never hits this.
