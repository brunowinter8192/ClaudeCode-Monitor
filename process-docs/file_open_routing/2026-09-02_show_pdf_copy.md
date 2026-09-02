# `show` Opens PDFs From a Read-Only Copy (2026-09-02)

## Problem

`show <file>` hands the original repo path to macOS `open`. For PDFs the default app is
Preview, which re-encodes the file on open through its autosave/versions machinery. Observed in
wise2627 on 2026-08-28: a merely displayed archive PDF grew from 256,415 to 257,026 bytes and
git reported it modified. The archive's whole point is byte-identical attachments.

## Where `show` actually lives

`~/.local/bin/show` is a dangling symlink to `Meta/blank/bin/show`; that directory no longer
exists (`dev-sync` in the same bin dir is dangling the same way). The shell skips the dead link
and resolves `show` from the last PATH entry, the iterative-dev plugin cache. Source of truth is
therefore `iterative-dev/bin/show`, deployed via `plugin-publish`.

## Decision

Scope limited to PDFs, because Preview is the only viewer with a confirmed rewrite on open. The
`md/markdown/txt` branch keeps the original path on purpose: the rule that a `show`n file picks
up later edits in place depends on it, and CotEditor does not rewrite on open. All other
extensions stay on the original path as before.

For `.pdf`, `show` copies the file to `${TMPDIR:-/tmp}/show-copies/<12-hex hash of absolute
source path>/<original basename>`, refreshes the copy on every call (`cp -f`), sets it to mode
444, and opens the copy. The hash keeps repeat calls on the same viewer document; the preserved
basename keeps Preview's title honest. The echoed line names the original and the copy.

## Verification

Worker-side: a throwaway script with a stubbed `open`, 9 assertions (bytes and mtime of the
original unchanged, copy at derived path with mode 444, stub received the copy path, second run
reuses the path, `.md` routing and echo unchanged). All pass.

Prod path after publish: a generated single-page PDF in a fresh git repo, real `show`, real
Preview. After 4 seconds `git status` is clean, the original's checksum is unchanged, and the
copy sits at the derived path with mode 444. The 2026-08-28 mutation could not be reproduced
against the copy path by construction, since Preview never sees the original.

## Left as is

The two dangling symlinks in `~/.local/bin` (`show`, `dev-sync`) are harmless while the plugin
cache is on PATH, but they point at a directory that no longer exists.
