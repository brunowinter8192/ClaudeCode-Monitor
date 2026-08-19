# Stable-Identity Codesign to Preserve TCC Grant Across Rebuilds (2026-06)

## Problem

Every `setup_py2app.py py2app` run re-signed `~/Applications/monitor-cc-menubar.app` ad-hoc
(`codesign -s -`). Ad-hoc signatures embed a per-build cdhash as the designated requirement (DR);
macOS TCC pins its stored Screen Recording grant to that DR. Each rebuild produces a new cdhash →
the stored grant no longer matches → the user had to re-approve Screen Recording in System
Settings after every single build.

## Root Cause (externally verified)

Source: nick-liu.com/posts/tcc-cdhash-trap — same failure pattern documented for yabai/skhd.
Ad-hoc signing yields `designated => cdhash H"..."` (binary-content-derived, changes per build).
Signing with a certificate identity — even self-signed, doesn't need to chain to a trusted root —
yields `designated => identifier "..." and certificate leaf = H"..."`. The leaf hash is a property
of the cert, not the binary, so it stays constant across rebuilds and the TCC grant survives.

## Fix

`_install_bundle()` in `setup_py2app.py` now:
1. Detects a signing identity named `monitor-cc Code Signing` via
   `security find-identity -p codesigning` (no `-v`) — gotcha confirmed empirically: `-v` filters
   by trust validation and a self-signed root reports `CSSMERR_TP_NOT_TRUSTED`, so `-v` would
   always show 0 identities even when the cert exists in the keychain.
2. If found: `codesign --sign "monitor-cc Code Signing" --force --deep <bundle>`.
3. If not found: unchanged ad-hoc fallback (`codesign -s - --deep --force`), with an explicit
   `WARNING: no signing identity found — TCC grant will reset on rebuild` printed to build output.
4. Always prints a `signed-with:` status line naming which path was taken, so a silent ad-hoc
   fallback is visible in build logs rather than discovered later via a TCC re-prompt.

## Verification State (as of this entry)

No `monitor-cc Code Signing` identity existed in the keychain on the dev machine at write time
(`security find-identity -p codesigning` → "0 identities found"). `_find_signing_identity()` was
verified standalone against the real keychain, confirming it correctly returns `False` and the
ad-hoc fallback path fires. The certificate itself was not created and the signed-with-identity
path was not exercised — that, plus the full `py2app` build + live TCC-grant-survival check, is
orchestrator-side follow-up: create the cert (e.g. via Keychain Access self-signed cert with name
`monitor-cc Code Signing`), run the real build, then confirm via
`codesign -d -r- ~/Applications/monitor-cc-menubar.app` that the designated requirement reads
`identifier "com.brunowinter.monitor-cc-menubar" and certificate leaf = H"..."` and that the
Screen Recording grant survives a subsequent rebuild.
