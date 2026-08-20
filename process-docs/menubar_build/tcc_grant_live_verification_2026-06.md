# Stable-Identity Signing — Live TCC Grant Survival Verification (2026-06)

Orchestrator-side follow-up closing the two verification gaps left open by the
stable-identity signing and copytree-symlinks entries in this area: the
signed-with-identity path had never been exercised, and no full build/verify/TCC cycle
had been run.

## Diagnosis Chain (why the first sign attempts failed)

Signing the installed bundle with the `monitor-cc Code Signing` identity failed twice
before the root cause was found:

1. "bundle format is ambiguous" — top-level `Python.framework` symlinks (`Python`,
   `Resources`) were full copies. Manual re-link moved the error to:
2. "unsealed contents present in the root directory of an embedded framework" —
   `Versions/Current` was ALSO a full 5.1 MB directory copy next to `Versions/3.14`
   (confirmed via `ls -la`: `drwxr-xr-x` instead of `lrwxr-xr-x`), duplicating the
   framework content.
3. Root cause: NOT py2app — `dist/monitor-cc-menubar.app` carried all three symlinks
   correctly. `_install_bundle()`'s plain `shutil.copytree` materialized them on deploy
   (fixed by `symlinks=True`, see the copytree entry in this area).

Manual repair (`rm -rf Current && ln -s 3.14 Current`) + re-sign then succeeded
immediately: `codesign --verify --deep --strict` rc=0.

## Signed-with-Identity Path — Verified

The `monitor-cc Code Signing` cert existed in the keychain at verification time
(`security find-identity -p codesigning` → 1 identity, `CSSMERR_TP_NOT_TRUSTED` as
expected for self-signed; the script's no-`-v` lookup matches it). A full
`setup_py2app.py py2app` run took the identity path — build output printed
`signed-with: monitor-cc Code Signing` — and the installed bundle showed:

- all three framework symlinks preserved (`lrwxr-xr-x`)
- `codesign --verify --deep --strict` rc=0
- designated requirement: `identifier "com.brunowinter.monitor-cc-menubar" and
  certificate leaf = H"1b55359044292a95debde98f2d9d92eab27e18c4"` — cert-derived,
  build-independent.

## TCC Grant Survival — Proven

Sequence: user granted Screen Recording once (the identity switch from ad-hoc
invalidated the old cdhash-pinned grant, expected one-time cost) → detection confirmed
working (`menubar.log` continuous `osc2_match` entries, zero `all_no_match` /
`cgw_list_empty`) → a SECOND full build + install + re-sign + bootstrap was run →
detection continued seamlessly after the service restart, no failure markers, no
re-approval prompt. As of this entry, the rebuild-invalidates-grant failure (three
builds, one manual re-grant observed live before the fix) no longer reproduces.
