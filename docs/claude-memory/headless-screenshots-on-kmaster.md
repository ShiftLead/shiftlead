---
name: headless-screenshots-on-kmaster
description: "How to screenshot a ShiftLead page on kmaster — Playwright with Chromium, script and shots in $SHIFTLEAD_SCRATCH/shots/"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 192b2355-2009-4e5e-ab33-69257956a53b
  modified: 2026-11-24T22:00:00.000Z
---

A screenshot and the script that takes it go in `$SHIFTLEAD_SCRATCH/shots/`, driven by headless Chromium under Playwright (design §4.6 *Where a session's working files go*, TD-2129). Playwright is installed at `~/ao-shots/pwlib` (read, never written), with its browser in `~/.cache/ms-playwright/`:

```bash
mkdir -p "$SHIFTLEAD_SCRATCH/shots"
PYTHONPATH=~/ao-shots/pwlib ~/.local/share/shiftlead-venv/bin/python "$SHIFTLEAD_SCRATCH/shots/<script>.py"
```

It waits for scripts, reads live values with `page.evaluate`, and shoots in either theme. The snap Firefox cannot see `/tmp` or the scratch, so it is no session's way to take a shot. A shot a PR shows is committed under `docs/mockups/reviews/`; the mockups have `docs/mockups/shot.sh`, whose default output is `$SHIFTLEAD_SCRATCH/shots`.

Against the live UI a shot stays read-only: GETs and reads, never a press. Presses go to a scratch home, `scripts/look_home.py` (TD-291), under `$SHIFTLEAD_SCRATCH` ([[scratchpad-too-long-for-unix-sockets]]). Paul's own screenshots arrive at `/mounted/dev/tmp*.png`; check the file's mtime, an old one is sometimes left there. See [[ui-review-screenshots]].
