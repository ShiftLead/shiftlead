# User Attention Board

Items that need the user to act or decide, plus in-flight work parked by a session. Sessions add entries **the moment they arise** and remove them when handled. Keep this file small — durable debt belongs in [technical_debt.md](technical_debt.md); this board is only "a human must act or decide."

All conventions — entry format and the `<host>` semantics, `Due:` dates and snoozing, the `Swept:`/`Swept-deep:` sweep stamps — live in `docs/cadence.md` §3 — the pinned agent-cadence's (`agent-cadence path cadence.md`; this repo pins it in `docs/cadence.toml`). That file is agent-cadence's (improvements reach this repo with a bump of the pin); this skeleton is SEED (yours, never overwritten), which is why the explanations do not live here (dev-cadence TD-17).

Format: `- [ ] YYYY-MM-DD (session <first-8-of-session-uuid> on <host>, or n/a) — what's needed. Context: TD-NNN / PR #N / branch. Due: YYYY-MM-DD.`

People: paul

## Needs the user

- [ ] decide 2026-11-13 (person) — /shiftlead-feedback: report mode and the reports' intake in the procedure, and the feedback report issue form. Context: TD-1796. Due: 2026-11-13. Decided: go ahead (by paul) (2026-11-13).
- [ ] decide 2026-11-13 (n/a) — Does the feedback report issue form open on GitHub with its title, warnings and one Report field, from the address the procedure gives? Context: TD-1796 decision (paul). Due: 2026-11-16. — Paul, 2026-11-13: This paragraph needs work - it is tough for a human to read. Lets drastically reduce the information here, and organize/format it to be conducive to a human reader: It holds the findings you approved: for each, its area, what and fix sentences and count (and the entry it recurs from), the known entries you counted, and once, the shiftlead commit your install runs, its day, the window's length in days, the number of seats read and the run's noise. It holds no transcript text but the sentences you approved. An edit after you submit keeps the earlier text in the issue's edit history, which anyone who can see the issue can open. The scrub takes out only the names it knows, as it spells them, and the patterns it matches. Only your read of the whole report catches what it cannot: a name spelled another way, a branch, a person's name, and private work described in plain words (a feature, a customer, a private entry's subject). Paste the report's text as the run wrote it, everything after its first line, which is the title. Never change it by hand: each sentence stands twice, in the table and in the block the intake reads. Change a finding by answering edit in the run, which writes the report again. Answers: Works | Not right: <what>. Lifts: Works | Not right: <what>.
  - **Context:** Built in #3775. Open https://github.com/ShiftLead/shiftlead/issues/new?template=feedback-report.yml&title=feedback%20report%3A%20abcdef0%20%C2%B7%203%20findings while signed in and submit nothing; GitHub lists no issue forms by API and redirects a signed-out read to login.
  - **Question:** Does the form open with the title feedback report: abcdef0 · 3 findings, its warnings and one required Report field?
  - **Recommended:** Works.
- [ ] act 2026-11-13 (n/a) — Once TD-1788's PR is merged and the checkout ao-grind starts from is on a main that holds it, stop and start ao-grind when no member holds a claim in progress (or say when you next will), so designer-ao-1 starts at its 150k context bound; only you can do this. Context: TD-1788. Due: 2026-11-20.
  - **Context:** The bound is written on the record at a start and carried through restarts and Apply, so only a Stop and Start of the team reaches the designer, which is the person's to press. When you close this line, give the time of that start: a session that sees it closed writes it on TD-1777's Log (ledger.py note TD-1777 "designer 150k from <time>"; else the day it closed), where the trial splits the designs by bound.
- [ ] watch 2026-11-13 (n/a) — Once #3689 is live, read a team card's TDs in motion on the live Sessions page (headless GET): a claim whose PR has an open ask at the techlead reads a REVIEW chip, and one whose PR nobody has asked reads its holder's BUILD or DESIGN; close with what was read, or ledger what is wrong. Context: none. Due: 2026-11-15.
- [ ] decide 2026-11-06 (n/a) — Run ao td add --repo shiftlead from a shell on the contractmatch node: does it print a message id (look m-54bb05fa8c71)? Context: TD-1404 decision (paul). Due: 2026-11-10. Answers: Works | Not right: <what it printed>. Lifts: Works | Not right: <what it printed>.
  - **Context:** TD-1404 is the live check of #2977: a person shell on a node hands an entry into another repo by name, resolved at the home. Only a real node shell shows it, and a session never presses it.
  - **Question:** From a shell opened from Focus on the contractmatch node, does ao td add --repo shiftlead "TD-1404 live check: ignore" print a message id?
  - **Recommended:** Works.
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
- [ ] act 2026-11-03 (session `grinder-ao-2` on kmaster) — **Once #2820 is promoted, turn on push from your iPhone and confirm one delivery through Apple's push service:** open the `https` address in Safari, Share → Add to Home Screen, open shiftlead from the home screen, Settings → **Push** → **tell me on this device**, allow notifications, then **Send a test to this device** — a notification should arrive, and a tap on it should open the Inbox in the app. The PR's tests stub the browser; only your phone can show Apple's push service takes the home's key. If it fails, the card's line under the device says why (*last failed …*); mark this with what it said. Context: TD-1305 / PR #2820. Due: 2026-11-04.

## In-flight (parked by a session)

- (none)
