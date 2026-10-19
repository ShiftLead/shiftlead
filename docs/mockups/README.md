# Mockup sources

`gen.py` emits the `.dc.html` artboards and `canvas.json` for the design canvas at
https://claude.ai/code/artifact/0e14af3a-5e5a-4d9c-88b2-74205c394c04 (Claude Design preview).
Edit `gen.py`, run it, then `./shot.sh` for a quick headless-Chromium look (PNGs in /tmp/shiftlead-shots), then re-seed
The artboards are plain HTML inside `<x-dc>`; to preview one locally, move the `<helmet>` contents
into `<head>`, drop the wrappers, and open it in a browser (see the session that built them).

**Checked-in artboards.** `OrgTeamFirst.dc.html` and `RepoPage.dc.html` are not generated: they were drawn on a Design canvas with Paul (TD-176, 2026-09-26) and copied in, so `gen.py` lists them in `LAYOUT` and leaves their files alone. Edit them by hand, or on the canvas and copy again; `shot.sh` renders them like any other. `reviews/2026-10-18-repo-stage-board*.png` are TD-900's renders of the Repo page as a board by stage, drawn from the live `ao --json repo` reading by a script of that session; `RepoPage.dc.html` is the page before it.
