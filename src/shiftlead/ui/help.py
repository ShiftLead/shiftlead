"""The help text (design §4.5a *The help text*, §4.5 screen 10 *Help*; TD-157, built by TD-167).

What the *i* marks, the `title` tooltips and the Help page say: one paragraph per control — *what it
does · when you would press it · what it does not do*. **This table is the one source in the code**,
and `tests/test_help.py` holds it equal to the design's list word for word and key for key, so the
design is the one place the text is written. A control's `title` is its paragraph's first
sentence; a mark's panel and the Help page carry the whole. Fixed text in the source, never a
session's (TD-071 item 8).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Help:
    key: str  # the control's id: the Help page's heading anchor, and what a template asks for
    name: str  # the control as the design names it
    where: str  # where it sits, in the design's words
    text: str  # the paragraph, verbatim


HELP: tuple[Help, ...] = (
    Help(
        "start",
        "Start",
        "team card",
        (
            "Runs the team again from its definition: every check first, then the concluded sessions closed under the "
            "wrap-up's own safety check, then the members, each started on its brief, and the manager written closed "
            "when it is on call or started when it stands. Press it to run the team again — after a wind-down, or when "
            "a run has concluded and you want the next. It is not a message: a running session is mailed with Message…,"
            " and a session holding uncommitted or unpushed work refuses the start instead of being closed."
        ),
    ),
    Help(
        "wind-down",
        "Wind down",
        "team card",
        (
            "Sends the wrap-up to every member and then to the manager: each finishes what it holds, pushes, "
            "and exits. Press it when the team should stop after the work in hand, not in the middle of it. "
            "It kills nothing — Stop now does — and forgets nothing."
        ),
    ),
    Help(
        "stop-now",
        "Stop now",
        "team card",
        (
            "Kills every session carrying this team's badge, at once, whatever it holds. Press it when "
            "waiting for a wind-down is worse than losing the turn in flight. Worktrees and unpushed work "
            "stay on disk under the cards, which read exited; Forget is a separate press."
        ),
    ),
    Help(
        "fold",
        "the fold",
        "*n sessions* on a team's card, and a click on its header",
        (
            "Shows or hides a team's cards and its summary; a stopped team's are folded away by default, and its "
            "summary draws only the facets that hold something. "
            "Press it to see what the team left — its repo's numbers, the claims still held, what each member "
            "last said it was doing — to read their mail, or to Forget them. It changes nothing on any record; "
            "which teams you have unfolded is remembered in this browser."
        ),
    ),
    Help(
        "who-for-what",
        "who for what",
        "a team's help panel",
        (
            "Lists whom to write to for what on a team: in the team's help panel, under this paragraph, one line "
            "for each role its definition gives a message line, with the session that holds it. Read it before "
            "you press Message…, to pick the session whose line fits what you have to say. It is the definition's "
            "words and nothing to press, and a team whose roles carry no line has none: Message… on a card opens with "
            "that session's own line."
        ),
    ),
    Help(
        "definition",
        "the Definition line",
        "a team's help panel",
        (
            "Says where this team is defined and how its shape is changed: Members… adds or removes a member "
            "line and sets how many sessions each line runs, Open file opens the file that defines it, and Flow "
            "on Settings → goes to the flow it follows. Open it when the team should be shaped differently — "
            "another member, another flow — rather than run differently. It changes nothing by itself, and a "
            "team a repo defines is changed by a pull request to that repo, so its Members… opens with Add "
            "member and Remove disabled, the reason beside them, and only its − / + live."
        ),
    ),
    Help(
        "not-concluded",
        "not concluded",
        "a live team's help panel, its Definition line",
        (
            "Says why this team has no Start yet: one clause for each session that keeps it from reading "
            "concluded — one that is working, one idle that has not declared, one that crashed or wants a "
            "restart, one waiting on your answer to its question. Read it to see what to wait for, or which "
            "session to message or close, before the team can be started again. It is read from the sessions' "
            "records and your Inbox each time the page is drawn and is nothing "
            "to press: Wind down and Stop now, on the team's header, are the controls for it."
        ),
    ),
    Help(
        "forget",
        "Forget",
        "a card's foot, the exited banner",
        (
            "Drops this session's record: the card, its report line and its mail. Press it when a finished "
            "session's card is clutter — its work merged, or pushed and accounted for. It stops nothing, "
            "since a live session offers no Forget; the worktree and the run log stay on disk, and the "
            "conversation stays in the tool's own files, where the Resumable list finds it. On a team the "
            "seat stays: the definition names it, and Start fills it again."
        ),
    ),
    Help(
        "forget-all",
        "Forget all",
        "team card",
        (
            "The Forget of every exited or closed card of this team, in one press. Press it when the team's "
            "run is over and everything it pushed has landed. It never forgets a card carrying work that "
            "exists only on this machine — those it names, and you forget them one at a time with the flag in "
            "view — nor a seat on call."
        ),
    ),
    Help(
        "plus",
        "+ card",
        "team card",
        (
            "Starts a session of your own in this team, and changes no definition: the New session form "
            "opens with the team picked and Role at Interactive, so the session gets the team's host, repo, "
            "manager and techlead. Press it to work beside the team — on its repo, under its manager, its held "
            "PRs read by its techlead. Nothing is written to org.yml and no member is added: for a permanent "
            "member, Members…."
        ),
    ),
    Help(
        "kill",
        "Kill",
        "Focus header, *more ▾*",
        (
            "Ends this session's process now and destroys its pane; the record stays, reading exited, and the "
            "worktree stays. Press it when a session is stuck or running away and a Wrap up would not be "
            "read. It is not Close, which also reaps the worktree, and not Forget, which drops the record; "
            "both are still there after it."
        ),
    ),
    Help(
        "close",
        "Close",
        "*Close session* on a card's foot, the Focus side panel, *more ▾*",
        (
            "Kills the session; the record reads closed. It reaps the worktree it made, unless that would "
            "lose something; a kept worktree says why on the Session card. It is offered only when every "
            "line of Ready to close is green — Kill always is."
        ),
    ),
    Help(
        "wrap-up",
        "Wrap up",
        "Focus header, *more ▾*",
        (
            "Sends the wrap-up prompt — the one a policy sends before a stop — so the session finishes, "
            "pushes and ledgers what it holds, then ends its turn. Press it when you want the work saved "
            "rather than the process stopped. It kills nothing: the session ends when it says it has, and a "
            "stop time does the same on a clock."
        ),
    ),
    Help(
        "resume",
        "Resume",
        "the exited banner, a Resumable row",
        (
            "Starts the conversation again under this name, on this record: the same mail, a new process at "
            "the tool's composer. Press it when you want to continue a finished session's conversation. To "
            "only read it, press Transcript instead: a resume is a start, which a manager may act on and "
            "which has to be closed again."
        ),
    ),
    Help(
        "side-panel",
        "» put away",
        "Focus side panel",
        (
            "Puts the side panel away to a narrow rail, and the terminal takes its width; « or any of the "
            "rail's glyphs brings it back, a glyph opening its card. Press it when the terminal is what you "
            "want wide — on a laptop, or reading a long diff. It hides no prompt and changes no fold: Allow "
            "and Deny stay on the identity line, and the choice is this browser's, for every session."
        ),
    ),
    Help(
        "prompts",
        "Prompts",
        "Focus side panel",
        (
            "The prompts this conversation was sent, newest first, each with the first line of its reply. "
            "Press one to scroll the terminal back to it, with the reply under it; typing returns to the live "
            "screen. One no longer in the terminal's history opens in the Transcript instead."
        ),
    ),
    Help(
        "pane-link",
        "a URL is a link",
        "Focus pane",
        (
            "Ctrl+click (Cmd+click on a Mac) on an http:// or https:// URL in the terminal opens it in a new "
            "tab; the URL underlines when the pointer is over it. Press it to follow the pull request, the CI "
            "run or the page a session just printed, instead of copying it into the address bar. A plain "
            "click or a drag over it only selects, as before, and nothing is sent to the session."
        ),
    ),
    Help(
        "pane-hyperlink",
        "a hyperlink is a link",
        "Focus pane",
        (
            "Ctrl+click (Cmd+click on a Mac) on a label a program printed with a link behind it — Claude Code's "
            "*⧉ Team Spend by Seat* — opens that link in a new tab; the label underlines when the pointer is over "
            "it, and rest the pointer on it to see where it goes. Only an http:// or https:// link opens. A plain "
            "click or a drag only selects, and nothing is sent to the session."
        ),
    ),
    Help(
        "pane-path",
        "a path is a link",
        "Focus pane",
        (
            "Ctrl+click (Cmd+click on a Mac) on a file the session named — `src/x.py:12` — opens it in your "
            "editor, at the line where the editor's link takes one; it underlines only when the file is in the "
            "session's repo, which the host checks when you hover. A plain click or a drag selects, as before; "
            "without an editor button on the Session card there are no file links. It opens the session's folder "
            "first, so the file lands in the worktree's window, unless you turned that off under file link on the "
            "Settings page; your browser may ask twice until you tell it to always allow this site."
        ),
    ),
    Help(
        "disconnect-card",
        "disconnect card",
        "Focus",
        (
            "While the terminal reconnects, the spend the page last held: this session, its team and all teams, "
            "today and this week, as money and as tokens, a subscription's API-equivalent (≈$) apart from a "
            "metered profile's bill ($), the account's windows under them with their resets, and when the figures "
            "were read. It fetches nothing while the link is down and goes when the terminal paints; the Spend "
            "page has the live figures."
        ),
    ),
    Help(
        "soft-key-row",
        "soft-key row",
        "Focus pane",
        (
            "Keys under the terminal — Tab, Esc, the arrows, Enter and 1–9 — that type into the session as a "
            "keyboard would. Press one on a phone or a tablet, which has no such keys: Tab accepts Claude Code's "
            "suggestion, an arrow or a digit picks from a menu. It moves no focus, so the phone's keyboard stays "
            "as it is, and it is not there while the terminal is read-only."
        ),
    ),
    Help(
        "restart",
        "Restart",
        "the Inbox restart row, a card's *more ▾*",
        (
            "Puts this session back in its team's run as its launch record started it: closed if it is still "
            "there, then started again under the same name, team, lane and brief, unattended if it was "
            "started so, on a fresh prompt and with its mail. Press it when the host agent will not restart a "
            "member by itself and you want it working again. It is not Resume, which brings the conversation "
            "back attended, under you. It is refused, saying what is left, while its checkout holds "
            "uncommitted or unpushed work."
        ),
    ),
    Help(
        "idle-open",
        "idle · open work",
        "an Inbox row, a card's slot",
        (
            "A member that the host agent nudged once and that is still idle with its work open, in a team "
            "with no manager to read it. Open it to see what stopped it, then Send it a line or Wrap it up; "
            "Snooze sets the row aside and changes nothing on the session. The row leaves by itself when the "
            "session's state changes. A team with a manager shows no such row: the reading goes to the "
            "manager, and the card's slot says idle · open work either way."
        ),
    ),
    Help(
        "cadence-failed",
        "cadence check failed",
        "an Inbox row",
        (
            "A member's pull request that fails the repo's cadence check after the host agent told the member "
            "once, or that failed when it was already merged, which no new report cures. The row names the failed"
            " checks, and beside review says whether the techlead's reply was seen or the review is only recorded. "
            "Open the member to see what it is doing about it. Snooze sets the row aside. Dismiss removes it and "
            "keeps the reading on the record; a later failing read brings it back. The row leaves by itself when "
            "a later read passes."
        ),
    ),
    Help(
        "held-missed",
        "merged without its read",
        "an Inbox row",
        (
            "Two pull requests of one member that touched held paths and merged with no reply from the techlead "
            "they wait for. The first such merge is a note under FYI and one line to the member; this row is the "
            "second. The host agent undoes nothing: read what merged, and revert it if it should not stand. Open "
            "the member to tell it so. Dismiss removes the row and keeps the two on the record, so the next such "
            "merge is a note again."
        ),
    ),
    Help(
        "message",
        "Message…",
        "a seat's card, *more ▾*, Focus header",
        (
            "Mails a question or a note into this session's inbox; the session reads it when it next looks, "
            "and a question fills a seat on call. Press it to ask or tell a session something without typing "
            "into its terminal. It types nothing into the pane — Send does — and it starts no team: a stopped "
            "team is started by Start."
        ),
    ),
    Help(
        "switch-profile",
        "Switch profile…",
        "a `limited` card",
        (
            "Re-launches this session under another profile with its conversation carried over. Press it when "
            "the account it runs on is capped and another is not. It is a new process on the same record; "
            "Wait leaves the session where it is until the account resets."
        ),
    ),
    Help(
        "promote",
        "Promote",
        "Inbox row: promote",
        (
            "Makes main's head live for this repo: the home starts the repo's own promote run with it, and a "
            "note says when it is live. Press it when what is merged should be what runs, and on a held row "
            "once main holds the cure: a press that concludes ends the hold. It never goes back to an older "
            "commit — that is `ao promote --sha` or `--back` — and it is refused, in words, while a run is "
            "in flight, a failure stands, or the checkout is not clean on main."
        ),
    ),
    Help(
        "promote-now",
        "Promote now",
        "Inbox row: promote",
        (
            "Makes main's head live now while `auto` is on, without waiting for the home's own clock: the same "
            "press as Promote, the settle and the thirty-minute wait skipped. Press it when what is merged "
            "should run before the time the row names. It goes through checks that are not green, as your press "
            "does, and it is refused, in words, while a run is in flight, a failure stands, or the checkout is "
            "not clean on main."
        ),
    ),
    Help(
        "promote-snooze",
        "Snooze ▾",
        "Inbox row: promote",
        (
            "Sets this row aside until the time you pick: +1 day, +1 week or a date. Press it when you "
            "promote in batches and want to be left alone until then. It changes nothing at the home: more "
            "merges meanwhile do not bring the row back, and a snoozed failure or hold still stops the "
            "policy."
        ),
    ),
    Help(
        "promote-dismiss",
        "Dismiss",
        "Inbox row: promote",
        (
            "Clears the home's own mark on this repo: a failed promote first, and a rollback's hold when no "
            "failure stands. Press it once you have read the failure, or when what a rollback went back from "
            "may go live again. It moves nothing live: once neither stands, promoting goes on — under `auto`, "
            "to main's head at the next pass."
        ),
    ),
    Help(
        "work-start",
        "Start",
        "Inbox row: team start",
        (
            "Starts this team from its definition, exactly as the Start on its card does: every check first, then the "
            "members with their briefs, and the manager written closed when it is on call or started when it stands. "
            "When the team is running and the row names members that finished, it starts those members alone, each on "
            "its brief. Press it when the entries the row names are work you want the team to take now. It is refused, "
            "in words, where the card's Start would be or where a bound holds the members back, and it hands no entry "
            "to anyone: each member takes from its lane's shared list."
        ),
    ),
    Help(
        "work-snooze",
        "Snooze ▾",
        "Inbox row: team start",
        (
            "Sets this row aside until the time you pick: +1 day, +1 week or a date. Press it when the "
            "entries can wait and you want to be asked again then. It changes nothing at the home: the "
            "entries stay waiting, and more of them meanwhile do not bring the row back early."
        ),
    ),
    Help(
        "work-dismiss",
        "Dismiss",
        "Inbox row: team start",
        (
            "Marks the entries this row names as seen by the team's members, so they do not ask again. "
            "Press it when those entries are not a reason to start the team. It starts nothing and removes "
            "no entry from the ledger, and an entry filed later raises a new row."
        ),
    ),
    Help(
        "ci-open",
        "Open",
        "Inbox row: CI not starting",
        (
            "Opens this account's billing page on GitHub: the organisation's, or your own for a user account. "
            "Press it to see why Actions does not start, and to pay the bill or raise the spending limit. It "
            "changes nothing at the home: paying does not re-run a pull request, and Re-run is what starts the "
            "waiting checks."
        ),
    ),
    Help(
        "ci-rerun",
        "Re-run",
        "Inbox row: CI not starting",
        (
            "Asks GitHub to re-run the failed jobs of every run this row names, and says how many it asked for "
            "and how many GitHub refused. Press it once the bill is paid or the limit raised. The row stays, "
            "reading re-run asked, while those runs are queued or running, and a run that again does not start "
            "keeps it without telling you again."
        ),
    ),
    Help(
        "ci-snooze",
        "Snooze ▾",
        "Inbox row: CI not starting",
        (
            "Sets this row aside until the time you pick: +1 day, +1 week or a date. Press it when the bill will "
            "be paid later and you want to be left alone until then. It changes nothing at the home or on GitHub: "
            "the pull requests keep waiting, and the row is not told on Telegram while it is snoozed."
        ),
    ),
    Help(
        "on-work",
        "when work appears",
        "Settings page: Teams",
        (
            "Says what the home does when this team has wound down and its lanes then gain entries: ask you with a row"
            " in the Inbox, start the team itself, or nothing. While the team runs on, a member that finished and was "
            "closed is started alone when its lane gains an entry. Start the team is the default; pick ask me where "
            "you want to look first. A start it would make is still held back, the row saying why, by the usage line, "
            "a passed stop time, three starts in a day, a start in the last thirty minutes, or the team's balance "
            "line. A team that stopped is never started for its work; the Inbox says its lanes gained it — under "
            "Later if you stopped it yourself."
        ),
    ),
    Help(
        "balance",
        "balance",
        "Settings page: Teams",
        (
            "Stops this team's unattended members taking a new claim while its repo is over a line you draw: more "
            "open pull requests than a number, the oldest open longer than a time, or the techlead's queue past its "
            "bound. Turn it on when the team opens pull requests faster than they are read and merged, and set "
            "each line against the numbers under it, which are today's; a field left empty draws no line. Work in "
            "hand goes on and nothing is paused or closed, and turning it off removes a standing mark, which the "
            "team's manager and you are told as the line clearing."
        ),
    ),
    Help(
        "file-link",
        "file link",
        "Settings page: You",
        (
            "Has a file link open the session's folder in your editor first, then the file after the wait you "
            "set, so the file lands in the worktree's window. Turn the folder off if the pair misfires for you, or "
            "lengthen the wait if the file lands in the wrong window. It runs no command; your browser may ask "
            "twice until you tell it to always allow this site."
        ),
    ),
    Help(
        "telegram",
        "tell me on Telegram",
        "Settings page: You",
        (
            "Has the home send you one Telegram message when a session or a team is stopped until you answer and "
            "no page of shiftlead is open. Turn it on once the Doppler project/config that holds the bot's token "
            "and chat id is saved beside it, so a team's question does not wait behind a closed tab. It sends no "
            "text a session wrote, tells a row once and only after a minute, and tells nothing while a page is "
            "visible; off, nothing is sent."
        ),
    ),
    Help(
        "telegram-test",
        "Send a test",
        "Settings page: You",
        (
            "Sends one Telegram message from the home now, with the saved secrets and link, whatever the switch "
            "says, and prints the result beside the button. Press it after saving the card, to see that a message "
            "reaches your phone and that its link opens this page. It saves nothing and changes no setting, and "
            "it waits while the card has changes not yet saved."
        ),
    ),
    Help(
        "board-answers",
        "answers",
        "Inbox board row",
        (
            "Records the answer you press as your decision on this board item: it is written on the item's line "
            "as Decided, with today's date, in one commit landed on the repo's origin by a pull request the "
            "host agent opens and merges itself. Press the one you mean when "
            "the item asks you to choose and its answers are offered. It does not close the item and wakes "
            "nobody: the line stays on the board as its session's work order and the row moves to Waiting on "
            "them, coming back if no session acts on it in three days; your checkout catches up when it next "
            "pulls, and an answer in your own words is a Reply."
        ),
    ),
    Help(
        "board-go-with-it",
        "Go with it",
        "Inbox board row",
        (
            "Records the answer marked default as your decision on this board item, in one press: the same write "
            "as pressing that answer. Press it when the session's own recommendation is what you want. Nothing "
            "takes the default for you — an item nobody decides stays undecided — and the item is not closed: it "
            "stays on the board as its session's work order, and the row moves to Waiting on them, coming back "
            "if no session acts on it in three days."
        ),
    ),
    Help(
        "spend-view",
        "Spend · Shape",
        "Spend page",
        (
            "Turns the Spend page to the team's shape over the current day or week: per team its suggestions, its"
            " members by role as hours by class, and its queues, one per stage of its flow. Press it when a "
            "team's spend or its waiting makes you ask whether a different shape — more of one role, fewer of "
            "another — would do better. It only suggests: nothing on it changes the team, and a change of members"
            " is yours, through Members… on the team card."
        ),
    ),
    Help(
        "spend-picks",
        "Day · Week · Month",
        "Spend page",
        (
            "Picks the period every figure on the page reads — a day, a week from Monday, or a calendar month — "
            "and the size of the chart's bars; beside it All or a team's chip picks whose spend is drawn, and ‹ ›"
            " step to the period before or after. Press them to see which teams and which sessions spent the "
            "quota, and when; the picks are carried in the page's address, so a link opens where it was. They "
            "change nothing but the view: no weight, no setting and no session is touched."
        ),
    ),
    Help(
        "spend-bar",
        "a bar",
        "Spend page: Over time",
        (
            "Picks the period the bar stands for, as ‹ › do, and every table under the chart reads it; its hover "
            "lists what the bar is made of. Press the bar where spend jumped, to see who spent it. A dashed bar "
            "is a period before the seat ledger began and cannot be picked, and a press charges, moves or resets "
            "nothing."
        ),
    ),
    Help(
        "usage-chip",
        "usage",
        "Sessions top bar, every page",
        (
            "Opens the Spend page on All: which teams and which sessions spent the quota, over time. Press it "
            "when the chip's number climbs faster than you expected. The chip shows each account's worst quota "
            "window, the rest on hover, and a press changes no reserve and pauses nothing."
        ),
    ),
    Help(
        "up-next-number",
        "the number",
        "Queue page: Up next",
        (
            "Is the card's place among the Up next cards with an entry in its repo, from 1, so two repos' first "
            "cards both read 1; where the home reads more than one repo each number carries its repo's name, and "
            "a card whose entries span repos carries one per repo. Read it as the order that repo's lanes pick in, "
            "the lowest number first — on a card spanning repos you never moved, a lane's own order can differ. "
            "It is not a control: a card moves by its grip or ⤒ ↑ ↓, and a Waiting or In progress card has no "
            "number."
        ),
    ),
    Help(
        "wait-column",
        "the wait column",
        "Queue page: Waiting",
        (
            "Shows what the card waits for — a date, an event, settling, a build not yet live, or blocked — and "
            "the place it would take in Up next once the wait ends. Read it to know when a card nobody can pick "
            "now comes back, and where. It is not a control: a Waiting card has no grip and no ⤒ ↑ ↓, and it "
            "returns to Up next by itself when the wait ends."
        ),
    ),
    Help(
        "read-n",
        "Read n",
        "Queue card",
        (
            "How many things on this card are for reading only — answers given for you, answered questions, notes. "
            "Open the card to see them."
        ),
    ),
    Help(
        "card-start",
        "Start session",
        "Queue card",
        (
            "Starts your own session on this card's team, on its top entry, with the card's entries as its "
            "context. It is drawn only where no item on the card asks you anything: each such item has its own. "
            "Reads Open session while yours is running."
        ),
    ),
    Help(
        "card-item-start",
        "Start session",
        "Queue card item",
        (
            "Starts your own session about this item: it opens on the card's entry, or on this entry where the "
            "item is one, with the item as its subject, to read first and walk through with you. Reads Open "
            "session while yours is on the card: the press goes there and copies the item's id for you to paste."
        ),
    ),
    Help(
        "card-answers",
        "answers, Answer…",
        "Queue card",
        (
            "Answers this item: each button says what it leads to, and the outlined one is recommended. Answer… "
            "sends your own words."
        ),
    ),
    Help(
        "card-dots",
        "⋯",
        "Queue card",
        (
            "The team's controls for this card, row or item: send it back to design, close it, open it on the Repo "
            "page, and an item's own — delete, pause, send to reviewer."
        ),
    ),
    Help(
        "board",
        "the board",
        "Repo page: Technical debt",
        (
            "Shows this repo's open work by stage: For you, one column per worker stage of the teams' flows, then "
            "Review and Merged, each heading saying who is on that stage. Read it to see whether a stage holds more "
            "work than people, or has nobody running at all. It moves nothing by itself — a card moves by its grip "
            "or ⤒ ↑ ↓ among this repo's cards in the same column — and an entry is edited in its file, never here."
        ),
    ),
    Help(
        "live-divider",
        "live divider",
        "Repo page: Merged",
        (
            "Draws one line across this list at the commit that is live: the closes above it, under not yet "
            "live, are merged on main but not yet in the running copy, and the ones below it are. Read it "
            "when you want to know whether a fix you saw merge is what runs now. It promotes nothing — the "
            "Inbox's promote row does — and while live cannot be read the list draws no line and says why."
        ),
    ),
    Help(
        "live-mark",
        "live mark",
        "Queue page: Recently completed",
        (
            "Marks each completed line not yet live while the commit that closed it is merged on main but not"
            " in the running copy, and live once it is. Read it before you try a fix you saw close, to know "
            "whether you will meet the old code or the new. It speaks of the close and not the code, and says"
            " nothing in a repo that does not promote or while live cannot be read."
        ),
    ),
    Help(
        "row-done",
        "Done…",
        "Queue card and Inbox: any open row",
        (
            "Closes the entry: your one line is written on the repo's board as done followed by your words, the "
            "sessions holding it and its PR's reader are told first, and its session archives it with your words."
            " Press it when the work is finished or no longer wanted and you want the ledger to say so. It merges"
            " no PR and edits no ledger by itself, and a design with open builds has none: it closes with its "
            "last build."
        ),
    ),
    Help(
        "row-back-to-design",
        "Back to design…",
        "Queue card and Inbox: any open row",
        (
            "Sends the entry back to design: your one line is written on the repo's board as back to design "
            "followed by your words, the sessions holding it and its PR's reader are told to stop first, and its "
            "session makes it a design-first entry for the designer. Press it when a build, a live check or an "
            "entry waiting on a sibling turns out to need its design settled again. It closes no PR — the build's"
            " open one stays named on the entry — and it is refused where no team's lane takes design-first."
        ),
    ),
)

BY_KEY: dict[str, Help] = {h.key: h for h in HELP}

# §4.5a the ***i*** mark row: one mark per control group, and the group's controls in its order
GROUPS: dict[str, tuple[str, ...]] = {
    "team": (
        "start",
        "wind-down",
        "stop-now",
        "definition",
        "not-concluded",
        "forget-all",
        "fold",
        "plus",
        "forget",
        "resume",
        "close",
        "message",
        "who-for-what",
    ),
    "focus": ("wrap-up", "kill", "close", "message"),
    "exited": ("resume", "forget"),
}
# where each group's *every control → Help* lands on the Help page
GROUP_SCREEN = {"team": "org", "focus": "focus", "exited": "focus"}

# §4.5 screen 10: the Help page, by screen in the §4.5a table's order, each paragraph once
SCREENS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "org",
        "Sessions",
        (
            "start",
            "wind-down",
            "stop-now",
            "fold",
            "definition",
            "not-concluded",
            "forget-all",
            "plus",
            "forget",
            "close",
            "message",
            "who-for-what",
            "switch-profile",
        ),
    ),
    (
        "focus",
        "Focus",
        (
            "wrap-up",
            "kill",
            "resume",
            "side-panel",
            "prompts",
            "pane-link",
            "pane-hyperlink",
            "pane-path",
            "disconnect-card",
            "soft-key-row",
        ),
    ),
    (
        "inbox",
        "Inbox",
        (
            "promote",
            "promote-now",
            "promote-snooze",
            "promote-dismiss",
            "work-start",
            "work-snooze",
            "work-dismiss",
            "ci-open",
            "ci-rerun",
            "ci-snooze",
            "board-answers",
            "board-go-with-it",
            "restart",
            "idle-open",
            "cadence-failed",
            "held-missed",
        ),
    ),
    ("repo", "Repo page", ("board", "live-divider")),
    (
        "queue",
        "Queue",
        (
            "up-next-number",
            "wait-column",
            "read-n",
            "card-start",
            "card-item-start",
            "card-answers",
            "card-dots",
            "live-mark",
            "row-done",
            "row-back-to-design",
        ),
    ),
    ("settings", "Settings", ("on-work", "balance", "file-link", "telegram", "telegram-test")),
    ("spend", "Spend", ("usage-chip", "spend-view", "spend-picks", "spend-bar")),
)


def first_sentence(key: str) -> str:
    """A control's `title` (§4.5a *The help text*): its paragraph's first sentence."""
    text = BY_KEY[key].text
    end = next(
        (i + 1 for i, c in enumerate(text) if c in ".!?" and (i + 1 == len(text) or text[i + 1] == " ")), len(text)
    )
    return text[:end]
