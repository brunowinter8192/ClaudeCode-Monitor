# Deploy Copy Must Preserve Symlinks — copytree(symlinks=True) (2026-06)

## Problem

`_install_bundle()` in `setup_py2app.py` deploys the py2app build output
(`dist/monitor-cc-menubar.app`) to `~/Applications` via `shutil.copytree(dist, dst)`.
`shutil.copytree` defaults to `symlinks=False`, which follows symlinks and materializes
their targets as full copies in the destination.

`dist/monitor-cc-menubar.app/Contents/Frameworks/Python.framework` (py2app's embedded
Python framework) is a correctly symlinked layout:
- `Python -> Versions/Current/Python`
- `Resources -> Versions/Current/Resources`
- `Versions/Current -> 3.14`

After the plain-`copytree` deploy, all three were full directory/file copies on the
installed bundle (confirmed live via `ls -la` on `~/Applications/monitor-cc-menubar.app`).
The duplicated framework content — real files sitting where the framework's own code-signing
expects a symlink — made `codesign --verify --deep --strict` fail with "unsealed contents
present in the root directory of an embedded framework". That breaks the stable-identity
signing flow (see the stable-identity signing work in `process-docs/menubar_build/`) that preserves the Screen
Recording TCC grant across rebuilds: a bundle that fails deep-strict verify is not a
faithfully re-signed copy of what py2app produced.

## Fix

One-line change at `setup_py2app.py:131`:
`shutil.copytree(dist, dst)` → `shutil.copytree(dist, dst, symlinks=True)`.
`symlinks=True` makes `copytree` recreate the symlink itself in the destination instead of
following it, so the deployed bundle is structurally identical to `dist/` — no other
behavior in `_install_bundle()` changed (signing, plist, launchctl bootstrap all untouched).

## Verification (as of this entry)

Standalone probe (not the production py2app build): built a temp source tree containing a
relative symlink (`Current -> Versions/3.14`, pointing at a real file `Versions/3.14`), ran
`shutil.copytree(src, dst, symlinks=True)` — the exact call now used in
`_install_bundle()` — and confirmed the destination's `Current` entry is a symlink
(`os.path.islink` → `True`, `os.readlink` → `Versions/3.14`, `ls -la` shows `lrwxr-xr-x ...
Current -> Versions/3.14`).

This proves `shutil.copytree(..., symlinks=True)` preserves relative symlinks as symlinks —
the library-call level. NOT exercised: a full `py2app` build + real deploy to
`~/Applications` + `codesign --verify --deep --strict` on the resulting bundle, which is the
actual failure this fix addresses. That full build/verify cycle is orchestrator-side
follow-up, same as the identity-signing verification gap noted in the stable-identity
signing work in this area.
