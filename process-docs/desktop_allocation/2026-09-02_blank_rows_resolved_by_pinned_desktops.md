# Blank desktop-number rows — resolved operationally by pinned desktops

**Date**: 2026-09-02

## Context

An open thread in this area asked for two things in the menubar panel: every main-session row
carrying its desktop number on every tick (no rows left blank while sibling rows resolve), and a
visible distinction between "could not resolve" and "never attempted".

## Decision

No code change. As of 2026-09, the user pins each main session to a fixed desktop by hand
(macOS "assign to desktop"), so the detection layer no longer has to chase windows across spaces
and the blank-row symptom does not occur in daily use. The thread was closed on that basis.

## What stays open

The two-state distinction (unresolvable vs. never attempted) was not built. If pinned desktops
stop being the operating mode, the detection code in `src/menubar/desktop_detection.py` and the
history in this area are the starting point.
