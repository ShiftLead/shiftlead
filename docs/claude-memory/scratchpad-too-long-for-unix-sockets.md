---
name: scratchpad-too-long-for-unix-sockets
description: A scratch SHIFTLEAD_HOME or socket goes under $SHIFTLEAD_SCRATCH, whose path fits a unix socket; never ~/.cache, /var/tmp or the old Claude scratchpad
metadata: 
  node_type: memory
  type: project
  originSessionId: d736f01f-1c5a-4673-b729-0c19c1bc45db
  modified: 2026-11-24T22:00:00.000Z
---

A ShiftLead session's own scratch, `$SHIFTLEAD_SCRATCH` (also its `TMPDIR`), has a path short enough for a unix socket, so a scratch `SHIFTLEAD_HOME` goes at `$SHIFTLEAD_SCRATCH/home` (design §4.6 *A session's scratch*, *Where a session's working files go*, TD-2129). In 2026-09 the Claude Code scratchpad (`/tmp/claude-1000/…/scratchpad/…`, about 130 bytes) failed with `OSError: AF_UNIX path too long` when the host agent bound `agent.sock`, and sessions worked round it with `~/.cache/ao<topic>`; that place is no longer used.

**Why:** unix socket paths are capped at 108 bytes, and anything written outside the scratch lies where no sweep looks.

**How to apply:** a scratch home or a socket: `$SHIFTLEAD_SCRATCH/home`. A test run: pytest's default under `TMPDIR` (TD-2097 keeps it within the limit), or a `--basetemp` of at most 60 bytes under the scratch (`$SHIFTLEAD_SCRATCH/bt`). Nothing else is written to `~/.cache`, `/var/tmp` or `~/ao-shots`. Related: [[unattended-workers-run-inside-shiftlead]], [[headless-screenshots-on-kmaster]].
