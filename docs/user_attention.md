# User Attention Board

Items that need the user to act or decide, plus in-flight work parked by a session. Sessions add entries **the moment they arise** and remove them when handled. Keep this file small — durable debt belongs in [technical_debt.md](technical_debt.md); this board is only "a human must act or decide."

All conventions — entry format and the `<host>` semantics, `Due:` dates and snoozing, the `Swept:`/`Swept-deep:` sweep stamps — live in `docs/cadence.md` §3 — the pinned agent-cadence's (`agent-cadence path cadence.md`; this repo pins it in `docs/cadence.toml`). That file is agent-cadence's (improvements reach this repo with a bump of the pin); this skeleton is SEED (yours, never overwritten), which is why the explanations do not live here (dev-cadence TD-17).

Format: `- [ ] YYYY-MM-DD (session <first-8-of-session-uuid> on <host>, or n/a) — what's needed. Context: TD-NNN / PR #N / branch. Due: YYYY-MM-DD.`

People: paul

## Needs the user

- [x] act 2026-11-11 (n/a) — Stop the stray agentorc-agent serve on kmaster (pid 976328, up 61 days, from ~/agentorc/.claude/worktrees/tdgrind-ao-1, its home /tmp/ao_manual_test deleted): it may be a second caller of the usage endpoint on your login (TD-1589); no session may signal a process it did not start. Context: TD-1589. Due: 2026-11-12. Closed: 2026-11-11.
- [ ] decide 2026-11-11 (n/a) — Will you run ao schedule ao-grind reset --profile grind --window week from your own shell, so ao-grind starts at each weekly reset and the next Thursday reset is read as TD-133's check? Context: TD-133 decision (paul). Due: 2026-11-18. Answers: Yes — I ran it | No — drop the check. Lifts: Yes | No.
  - **Context:** TD-133 is the live check of the weekly-reset start (#2873). A session cannot read or set a schedule, so only you can set it; the gate moved from the old decision form to this item (TD-1584).
  - **Question:** Run the schedule command from your own shell, or drop the check?
  - **Recommended:** Yes — I ran it, if you want ao-grind to restart at each weekly reset; a grinder then reads the reset after it.
- [ ] decide 2026-11-11 (n/a) — On your phone, does a pinch change the columns once and survive a reload, and does a swipe on the strip walk the records? Context: TD-1301 decision (paul). Due: 2026-11-18. Answers: Works | Not right. Lifts: Works | Not right.
  - **Context:** TD-1301 is a live check of the phone Focus (TD-003): only your phone shows it. You were asked in the look m-47ff5ed1cf57 (2026-11-02); this item carries it on the board (TD-1584).
  - **Question:** On your phone, does a pinch change the columns once and survive a reload, and does a swipe on the strip walk the records?
  - **Recommended:** Works if it does; Not right and a grinder files what is wrong.
- [ ] decide 2026-11-11 (n/a) — On your phone, does the key bar answer a Claude Code menu by digit and by the drag pad? Context: TD-1300 decision (paul). Due: 2026-11-18. Answers: Works | Not right. Lifts: Works | Not right.
  - **Context:** TD-1300 is a live check of the phone Focus (TD-003): only your phone shows it. You were asked in the look m-47ff5ed1cf57 (2026-11-02); this item carries it on the board (TD-1584).
  - **Question:** On your phone, does the key bar answer a Claude Code menu by digit and by the drag pad?
  - **Recommended:** Works if it does; Not right and a grinder files what is wrong.
- [ ] decide 2026-11-11 (n/a) — Open Focus from your phone's home screen: does the one screen (strip, Watching line, input bar, ⋯ sheet) work? Context: TD-1299 decision (paul). Due: 2026-11-18. Answers: Works | Not right. Lifts: Works | Not right.
  - **Context:** TD-1299 is a live check of the phone Focus (TD-003): only your phone shows it. You were asked in the look m-47ff5ed1cf57 (2026-11-02); this item carries it on the board (TD-1584).
  - **Question:** Open Focus from your phone's home screen: does the one screen (strip, Watching line, input bar, ⋯ sheet) work?
  - **Recommended:** Works if it does; Not right and a grinder files what is wrong.
- [x] decide 2026-11-11 (session `designer-ao-1`) — Should TD-1470's builds (a home check that raises a stuck row on an open question or a decided board line no live session can act on) go ahead as your Hold revised them, with no PRs, after TD-1571's four rounds, the last of which raised nothing build-changing? Context: TD-1470 decision (paul). Parts: TD-1496, TD-1497, TD-1498. Due: 2026-11-14. Answers: Go (default) | One more round | Hold: <note>. Decided: Go (by paul) (2026-11-11). Closed: 2026-11-11 — lifted.
  - **Context:** TD-1470 designs a home check that tells you when open work has no live session able to act on it. Your Hold (2026-11-10) asked to drop PRs; TD-1571 did, in PR #3330, and its four review rounds (Fable, then Sonnet, each with a fact-check) ended at the cap, the last review raising nothing build-changing.
  - **Question:** Go with the builds as revised: the check reads an open question to a session and a decided board line only; a line you are already asked about is not read; PRs come back with TD-1572.
  - **Recommended:** Go — every build-changing fix has been read by a review; no fix is unread.
- [x] decide 2026-11-10 (session `designer-ao-1`) — Should TD-1576's build (an option-free reply road, so the Gemini fact-check seat no longer stops for you on every reply) go ahead as written after four review rounds ended at the cap? Context: TD-1576 decision (paul). Parts: TD-1582. Due: 2026-11-12. Answers: Go (default) | One more round | Hold: <note>. Decided: Go (by paul) (2026-11-11). Closed: 2026-11-11 — lifted.
  - **Context:** TD-1576: Gemini CLI 0.66.0 asks before any command carrying an option it has seen in earlier output, under yolo and whatever a policy says, so the fact-check seat stopped on every reply. The design gives it an option-free road: ao reply <id> '<text>', ao inbox read as text (now marking an entry request for every reader), a brief with no option the tool would stop on, the seat asking nobody, and the home refusing an ask --pr to a fact-check seat. Four review rounds (a fact-check, Fable, then Sonnet each) ended at the cap. Build-changing findings from the design reviews per round: 6, 3, 4, 3 (the fact-checks apart: 0, 1, 0, 0). The last review (Sonnet, round 4) found nothing build-changing; the closing fact-check raised 4 minor. The review record is docs/reviews/TD-1576.md, the plain-words synopsis docs/synopses/TD-1576.md.
  - **Question:** Should TD-1576's build go ahead as written, get one more round, or is this the wrong design (Hold, with a note)?
  - **Caveats:** Fixes no review has read: none build-changing (F51 and the closing fact-check's four are minor). Recurring topics, each named because a later round raised a build-changing finding on an earlier fix: (1) the reply text on the command line — F6, F14, F20, F24, F33, F35 (a heredoc splits; the text is one single-quoted word with no apostrophe, its own examples kept so, a test holding it); (2) an ask carrying a PR — F37, F39, F43, F48 (first left unanswered, which would refill the seat; now refused at send, before the green read and any route-around, a flow stage naming the role not followable). Is this the wrong design? The author's position: no — the guard is the tool's and cannot be lifted, every round narrowed the same road, and the last review found nothing build-changing.
  - **Recommended:** Go — every build-changing fix has been read by a later review. Otherwise: One more round runs a fifth fact-check, Fable and Sonnet on PR #3289; Hold: <note> if the road should differ (for example, a reply read from a file).
- [ ] decide 2026-11-06 (n/a) — Run ao td add --repo shiftlead from a shell on the contractmatch node: does it print a message id (look m-54bb05fa8c71)? Context: TD-1404 decision (paul). Due: 2026-11-10. Answers: Works | Not right: <what it printed>. Lifts: Works | Not right: <what it printed>.
  - **Context:** TD-1404 is the live check of #2977: a person shell on a node hands an entry into another repo by name, resolved at the home. Only a real node shell shows it, and a session never presses it.
  - **Question:** From a shell opened from Focus on the contractmatch node, does ao td add --repo shiftlead "TD-1404 live check: ignore" print a message id?
  - **Recommended:** Works.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Will you run a Claude Code session in a throwaway profile that prints a long reply, then drag, put away and resize its Focus window, so a session can compare tmux's scrollback before and after and count the lines cut off? Context: TD-794 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: The Focus terminal shows a reply's lines cut off mid-word, and a block of it twice: a resize makes Claude Code repaint over lines tmux has already kept, and no refresh can mend them.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Will you run a Claude Code session in a throwaway profile that prints a long reply, then drag, put away and resize its Focus window, so a session can compare tmux's scrollback before and after and count the lines cut off?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Once projects are headings over repos (TD-722), will you put samscrape and contractmatch under one ContractMatch project in `org.yml`? Context: TD-723 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: Backfill TD-722: samscrape and contractmatch under one ContractMatch project.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Once projects are headings over repos (TD-722), will you put samscrape and contractmatch under one ContractMatch project in `org.yml`?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Will you give ShiftLead a Telegram bot and a Doppler config of its own (`shiftlead/prd`), so its notes stop going through samscrape's bot? Context: TD-673 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: ShiftLead's Telegram notes go through samscrape's bot (`secrets: samscrape/prd`): give ShiftLead a bot and a Doppler config of its own.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Will you give ShiftLead a Telegram bot and a Doppler config of its own (`shiftlead/prd`), so its notes stop going through samscrape's bot?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — When you want mail kept and searchable past its 12 hours, or inbox counts across thousands of entries, should the host agent move mail and session records into one SQLite file of its own? Context: TD-131 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: Mail, the board and the records are JSON and Markdown files read whole: fine at today's size, and no answer to search over history, counts per filter, or a retention longer than twelve hours.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** When you want mail kept and searchable past its 12 hours, or inbox counts across thousands of entries, should the host agent move mail and session records into one SQLite file of its own?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Will you finish the look-and-feel pass on your design canvas (the Org page, the Inbox page and the state icons), so a design round can build from it? Context: TD-071 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: Org page review, 2026-09-18 — what was built, and the ideas that were not.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Will you finish the look-and-feel pass on your design canvas (the Org page, the Inbox page and the state icons), so a design round can build from it?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Will you run one attended Claude Code launch in a fresh worktree of a repo whose main checkout is trusted, to see whether the trust dialog still appears? Context: TD-005 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: `pretrust()` can lose a concurrent Claude Code rewrite of `.claude.json`.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Will you run one attended Claude Code launch in a fresh worktree of a repo whose main checkout is trusted, to see whether the trust dialog still appears?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] decide 2026-11-05 (session `grinder-ao-2` on kmaster) — Once the review rounds converge and the three parts are built, will you use Focus on your phone for a real session and say whether it is the phone view you want? Context: TD-003 decision (paul). Due: 2026-11-19. Answers: Yes | Not yet. Lifts: Yes.
  - **Context:** The ledger entry is: Phone layout: Focus as one screen — the terminal, the strip, the key bar and the input bar, everything else in sheets.
    - It names you as its owner. Owner is about to stop holding an entry (TD-1375), so TD-1374 gated it with decision (paul), and this item is how you release it.
  - **Question:** Once the review rounds converge and the three parts are built, will you use Focus on your phone for a real session and say whether it is the phone view you want?
  - **Recommended:** only you can know: Yes lifts the gate and the entry goes ahead; Not yet keeps it waiting on you.
- [ ] act 2026-11-03 (session `grinder-ao-2` on kmaster) — **Once #2820 is promoted, turn on push from your iPhone and confirm one delivery through Apple's push service:** open the `https` address in Safari, Share → Add to Home Screen, open shiftlead from the home screen, Settings → **Push** → **tell me on this device**, allow notifications, then **Send a test to this device** — a notification should arrive, and a tap on it should open the Inbox in the app. The PR's tests stub the browser; only your phone can show Apple's push service takes the home's key. If it fails, the card's line under the device says why (*last failed …*); mark this with what it said. Context: TD-1305 / PR #2820. Due: 2026-11-04.

## In-flight (parked by a session)

- (none)
