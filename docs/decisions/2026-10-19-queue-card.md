# ADR 2026-10-19: The Queue card — three wants, three verbs, a Waiting group, items that lead with one sentence

Status: **agreed, held for Paul's lift** — the review rounds converged on 2026-10-19 (round 6 READY, below);
drawn with Paul the same day over an afternoon of rounds on two review pages built from the live ledger ([the card](../mockups/reviews/2026-10-19-queue-card.html),
[the page](../mockups/reviews/2026-10-19-queue-redesign.html), its shot
[`2026-10-19-queue-redesign.png`](../mockups/reviews/2026-10-19-queue-redesign.png)). TD-909 carries it; its
`Blocked by: decision (paul)` stands until Paul lifts it, then the designer's round writes it into §4.4 *The Queue: cards, and the rank that orders them*, §4.5 screen 12, §4.5a and §4.10, and the
build entries follow. Where this ADR and the design differ once that lands, the design is what is true.
It amends [ADR 2026-10-15](2026-10-15-queue.md), which stands for everything it does not touch: the one-card
rule, the top entry, rows, the rank, the Inbox split, the trial.

**Paul, 2026-10-19:** *We have many ways that the user's attention is needed: decision, question from
session, hold, etc. and there are multiple possible replies: reply, "start a session", hold, "put on the
board", etc. — I think we need to figure out how to simplify.* And: *there are lots of words all over the
place (yours to do, asks, etc), so I am relegated to reading everything in order, or skimming at my peril.
Then when I get to the actual description — it's written like someone took poor notes then handed them to
me.* And: *if I have a "Do" item I am going to start a session and have the AI do as much of it as
possible.* And: *Snooze and dates still make sense for inbox items, but they do not in an ordered queue.*

## Why
The Queue was built (TD-769–TD-771, merged 2026-10-16) and measured on 2026-10-19 (main at `02a6f447c`) with
the live ledger: 197 cards Up next, 82 of them amber, 11 with the status *waiting* (the blocked, settling and
no-lane cards, which §1 puts beside them, were not counted), the tallest card 3,212 px (TD-900: seven
*Answered for you* items drawn in the Inbox's full shape above its six rows), the median 138 px. Card 1 was
TD-748 itself, waiting on a date eleven days out and saying only *waiting*, headed by an FYI about a row
already done. The card has the right content and the wrong grammar: a dozen words for what it wants from
the person, a dozen controls whose meaning depends on a kind the person cannot see, and text written for
the writer.

## 1. Groups: Waiting, between In progress and Up next
The page has four groups, furthest through first: **Recently completed**, **In progress**, **Waiting**,
**Up next**. Waiting is **a predicate of its own in the `queue` reading, `waits`, read before any need** —
the card's status word (§4.4 *The card's status*: *needs you* > *steer* > *stalled* > *blocked* > *waiting*
> *ready*) is unchanged, and the group is read from `waits`, never from the status. **`waits` is true when
every open member that is not the person's own** — not `Owner: paul`, not `Blocked by: decision (paul)` —
**waits**: has a `Waits:` line, is a live check whose build is not live, is settling, is blocked by open
ids **once the person's own are set aside** (a child blocked only by the person's Do is not waiting: the Do
is its unblock; one blocked by the Do and by TD-x waits on TD-x — the shape of `_status`'s own test, which
sets the designer's decision aside before it looks), is blocked past the org's reach (the reading's `unreachable`: a `decision (<who>)` with `who`
neither the person nor the designer, an id ledgerboard cannot resolve), or is an entry no lane takes (its
`for_page` in `NO_LANE`: an *evaluation* or *other* entry, §4.4 *Repo facts*); and at least one open member
is not the person's own. **The person's own** are `Owner: paul`, `Blocked by: decision (paul)`, and a *held
(person)* entry. `waits` is a predicate of its own over the same inputs `_status` reads; it does not reuse
`_status`'s nested wait test, which stays as the status word *waiting*'s, and it reads the `unreachable` and
`NO_LANE` cases that `_status` returns *blocked* for before it tests waiting. So a card with a Decide or
Do item (§2) **is in Waiting when the rest of it waits**: the group says where the work is, the colour says
whether the person is in it. A card whose open members are all the person's own is Up next. A card In
progress is In progress, whatever `waits` says.

**Numbering.** Up next is numbered over its own cards alone, per repo as TD-901 says, with no gaps: the
pick order the repo's lanes read among what is pickable. A Waiting card is unnumbered and carries no grip
and no ⤒ ↑ ↓; its rank line is untouched, it stays a neighbour in the whole order (§4.4 *A move lands*: a
drop between two Up next cards may land either side of a Waiting card between them, which nobody sees), and
it says the place it would take today if its wait ended, *would be 1 in shiftlead*, one per repo for a card
spanning repos. `rank_move` refuses a Waiting card's ids and a Waiting neighbour, as it refuses an In
progress card's; §4.4's *Up next is every other open card* becomes *every open card that is neither In
progress nor Waiting*; the group's heading reads *Waiting (n)*, and *n of m* while a pick is on, as the
others do. When the wait ends the card is Up next at that place.

**The wait column.** Where Up next draws the number, a Waiting card draws, at the same size and strength
with the repo chip under it: the top entry's own `Waits:` date, *Oct 30*; else *event* when the top entry
waits on an event; else the earliest `Waits:` date among its open members (the first moment anything on the
card can be picked); else *event* when any member waits on one; else the word for the reason — *settling*,
*not live* (a live check whose build is not live), *blocked*. **The column and the phrase always come from a
leaf**: a member that waits for a reason of its own, never one that waits only on open ids — a card is
Waiting only when every chain of open ids ends in such a leaf, so one always exists — except a cycle of
open ids with no leaf (ledgerboard tolerates one; the key order breaks it), which is read as past reach:
the column says *blocked*, the phrase *blocked: TD-a and TD-b block each other*, from the cycle's
lowest-keyed member, and no builder asserts a leaf — and when several
leaves tie on the rule above, the one with the lowest key supplies both. Its status at the right is the
whole phrase for the same member: *waits until Oct 30*, *waits on
the next launch whose first hook is lost*, *settling*, *blocked: decision (techlead)*, *blocked: dev-cadence#TD-119
unresolved*, *blocked: no lane takes it*, *not live #1838* — for the leaf the column was read from. **The word *blocked* is kept** in the phrase for a card time will
not free, so a typo'd id or an outside decision does not read as a date to wait for; such a card is in
Waiting because nobody can pick it, and reads *blocked* so the person knows why. Up next is then what is
pickable now, needs the person, or is held by the person (*held (person)* stays in Up next, §4.5 screen 12).
The pick order lanes read is unchanged by the group; what changes for lanes is in §3 (Start session's
claim) and §8 (the trial).

## 2. Three wants
A card can want three things of the person, and the section names say which:

| Want | What it is today | Where it is drawn |
|---|---|---|
| **Decide** | an `ask` with or without answers; a `steer`, running (with its countdown and Go with it) or paused; a board line of kind `decide` or `look` (cadence §3.3; `act` moved to Do, §9); a `Blocked by: decision (paul)` hold (*Lift the hold* its answer); an entry with `Answers:` | the header, open, amber, counted |
| **Do** | an entry whose `Owner:` is the person (*yours*); a board line of kind `act`, *Done* its answer (§9); a red PR nobody holds that names one of the card's entries, in a repo no team services (§4.5a *Inbox row: red PR*; the card is In progress, its PR open) — the row stays in the Inbox, counted once there as today; the card draws it as a Do item, *#n red — Open*, counted in the pill only, never a second top-bar count, amber; no Snooze on the card, and Start session never chooses it (it is no entry) | the header, open, amber, counted |
| **Read** | FYI (notes, the trail, a `watch` or `fyi` board line), *Answered for you*, *Waiting on them* (an answered ask or steer, a decided line its session has not landed) | under the rows, **folded, with its count**, uncounted |

Decide and Do both colour the card amber and both are counted on its pill, *Decide 1 · Do 1*; the page
header counts them across the Queue, *Decide 12 · Do 70*. **These are counts of items, not cards, display
only: they enter no top-bar or rail number** (§4.4: a ledger row's need enters no count; the top bar's one
number is untouched and will not match them, which the header's hover says). Paul, 2026-10-19: *Do and
Decide coloring a card is good — it lets me know what is waiting on me. We have a large backlog currently,
and that's ok.* Read never colours; **a folded card's header carries a quiet *Read 7*** in grey at its right
edge, in no total, so an *Answered for you* item is never invisible — it exists so a confident wrong answer
cannot steer a team unseen, and the fold's count keeps that. Inside Read's fold each Inbox section keeps its
own line and its **Dismiss all** (§4.5a): *answered for you (7)*, *waiting on them (1)*, *fyi (2)*.
**A *held (person)* entry is no want**: the person owes nothing on it; its row reads *held (person) — why*
with **Release** in the ⋯ in place of Hold, and the card is not amber for it — §4.4 *The card's status* loses
its *needs you* from a *held (person)* row, and gains the word ***held (person)*** for a card whose
non-waiting open members are all held, between *stalled* and *blocked*, so such a card never reads *ready*
(a §4.4 edit of this ADR's). A held card with a waiting child is Waiting, teal, no want, and does not move; Start
session on it starts on the card's chosen entry (§3), and when that is the held entry a hold allows it — a
hold withholds from lanes only (§4.4 *Hold*). Two more design sentences change with this: §4.4 *A move
lands*' *a card the person holds is in Up next and moves as any other* and screen 11's *a held (person)
card is Up next and moves* each gain *unless a child of it waits (§1)*; and `rank.intent`'s refusal names the
group it refuses, *is Waiting, which does not move*, as it names In progress today. The Inbox's five section names stand on the Inbox (§4.5 screen 6); the card maps them to
these three, and this table is the whole map.

## 3. Three verbs
Whatever the item's kind, the person does one of three things, and the words are the same on every item:

- **Answer** — the item's answers drawn as buttons, the recommended one outlined (no caption: the outline
  is the convention), and **Answer…** for the person's own words. *Done* on a Do item, *Lift the hold* on a
  `decision (paul)` hold, *Go with it* on a steer, and the look's pair *Works* / *Not right…* (two answers
  the page draws by their words, §4.5a *Inbox row: a look*) are answers, drawn in this row, each taking the
  road its kind already has (§4.4 *Board write-back*, §4.5a *Inbox row: ledger entry*). No **Reply** word on
  a card: a reply on a ledger row is a work order, not a conversation, and the word hid that.
- **Start session** — **once per card, in its header** (amended by §9: on every Decide and Do item, the header's only where no item has one), plain (a filled button was too loud; Paul,
  2026-10-19), on the Repo page's card too (the one partial). It is the Do verb: *if I have a "Do" item I
  am going to start a session and have the AI do as much of it as possible, giving me easy copy/paste or
  instructions for the rest.* **It starts the person's own interactive session on the card's repo's team,
  with the card as its context.** The road is the ledger row's (§4.5a *Inbox row: ledger entry: Start
  session*), **widened**: `/api/ledger/start` takes `{repo, id, card}` and no longer requires the entry to
  be *for you*; in its place it checks that the entry is open and is the card's choice as the reading has
  it now — **`start`, the chosen entry's id on each card of the `queue` reading**, one value the button and
  the road both read (Do, `Answers:` and `decision (paul)` are ledger facts, so `sessionorc.queue` owns it). The entry the session is started on — its repo's team, its worktree `td-<n>`, its branch,
  and so the claim the tick derives — is **the card's Do ledger entry when it has exactly one (a red PR is never counted), else its first
  Decide ledger entry (an `Answers:` entry or a `decision (paul)` hold, by key), else the top entry**,
  **chosen by key alone, never by what is already claimed**, so two presses choose the same entry; a
  card spanning repos starts on that entry's repo's team and names the rest. **The claim is owned**: the
  person's session holds that entry while it lives — the claim is in the reading's `held`, the claims map, which is what
  the lanes read — the card is In progress, and the row carries the session's pill, reading *held by
  td-<n>* where it has a state word; a row of the person's keeps its need and a held row its *held
  (person)*, `_state`'s order (superseded 2026-10-30 by TD-1281: a row of the person's that their own
  session claims reads *with you in <name>* and is no want, design §4.4 *The card's status*). On a card with nothing of the person's the held entry is the top entry, taken
  from the lanes for as long as the session runs, which is the person's call. The opening prompt is **one template, `briefs/work.md`, reshaped**: its first sentence
  by `why_key` — *yours* and *decision* keep today's words, with *from the Queue* in place of *from the
  Inbox* when pressed on a card (the Inbox row keeps *Inbox*, and the §4.5a row's quoted text changes with
  it), and a third key, *card*, for any chosen entry that is neither `Owner: paul` nor a `decision (paul)`
  hold, reads *I opened this session from the Queue to work the card around TD-n*; then, for every key, **the
  id-list sentence** — *Its entries are: waits on me — <ids>; the rest — <ids>*, each `<repo>#TD-n`,
  comma-separated, *waits on me* the Decide and Do ledger entries (amended, §9: every Decide and Do item, by its id), either group *none* when empty (a card
  whose only want is a red PR has no such entry; amended, §9: a red PR is in it as `<repo>#<n>`) — ids only, never an entry's own words (§4.5a); then today's closing sentences unchanged (*check the code and the design for what is already
  built or decided*, *I drive this one*), so the three keys read in one voice. **The session's claim is the
  tick's derived one** from the branch `td-<n>` (§4.8): `reports.derive` writes it from the branch alone and
  never calls `claim_refusal`, which only a declared `ao progress claim` meets; `work.md` runs none, so a
  held or settling entry still starts — on a held entry the person's own start is the person's own window,
  the hold stays and the claim is derived anyway. §4.4 *Hold* gains that sentence (the design round's): *a
  derived claim is not refused — the person's own `td-<n>` session holds a held entry, and the hold still
  withholds it from lanes*. **The person's own
  session** is a record with `unattended: false` and no caller (§4.5a *Inbox row: ledger entry*); any other
  holder of the chosen entry, a lead's interactive session included, is *held by <name>*. With several of
  the person's own sessions on the card, Open session goes to the one holding the chosen entry, else the
  first by id.
  While **the person's own interactive session** holds any of the card's entries the button reads **Open
  session** and goes there, **whatever holds the chosen entry** — the button is once per card (amended, §9) and the
  person's session is where the card's work is; the road does the same before it starts anything, so a
  stale page's press never starts a second session on the card. With no session of the person's on the card
  and an unattended worker on the chosen entry, the button is absent, the row says *held by <name>*, and the
  road refuses a stale press with 409 *held by <name>* rather than handing the person that worker's Focus. The existing refusals (no
  servicing team, the name not free, the team on another host) still fall to the filled New session form.
- **⋯** — the team's controls, behind one visible mark on the card's header and on each row and item; **the
  header's ⋯ acts on the top entry, a row's on the row**, and Hold is in the header's only where the top
  entry is open and eligible (§4.5a *Repo page: Hold*):
  **Hold** (*keep the team off this*, the one "not now" that survives on a card, because it stops a lane
  and is not about the person) or **Release** on a held row, **Back to design…**, **Done…** on an entry
  (not an `Owner: paul` row, whose Done is an answer, and not a design with open builds, as today), **Open**
  on the Repo page (§4.5 screen 12 *any open row*); on an item, **Delete** on an ask (the decline),
  **Pause** / **Resume** on a steer, **Send to reviewer** on a look that is an open ask (§4.5a *Inbox row: a
  look*), and **Done** on a decided board line under *waiting on them*. The names inside are drawn on hover or focus of the header, row or
  item; **the ⋯ itself is always drawn**, at narrow width too, where there is no hover (superseded 2026-10-20 by TD-926: the ⋯ is bare at every width, its names in its `title`, its
  `aria-label` and its menu, since names drawn on hover rewrapped the title, so narrow width no longer
  differs — design §4.5 *A hover changes colour, never layout*). It is a control
  class of its own with a keyboard model (`Enter` opens, arrows move, `Esc` closes) and gets its own §4.5a
  row.

**No dates of the person's on a card.** No Snooze, no Put on the board, no Due. The rank is the snooze: a
card not wanted now moves down. Waiting is the ledger's own dates. The Inbox keeps Snooze, Put on the board
and `Due:` for what names no entry (§5). A Read item opened on the card keeps its Dismiss and Put on the
board, the Inbox's own, and **Overrule** on an *answered for you* item beside its Dismiss (§4.5a).

## 4. The header, the rows, and one renderer per kind with a card mode
- **The header's right edge** reads, in order: the move arrows, Start session and ⋯, a gap, then the facts —
  *n entries*, *Read n* when the card is folded and has Read items, and one status. The status ends the
  line. On an Up next card the status is the ledger's word or the amber pill with its counts; on a Waiting
  card the wait phrase, with the pill, *steer* or *stalled* beside it when the card has one, as an In
  progress card's sits beside *d/m done*; on an In progress card *d/m done* beside *in review #n*. The
  phrase ends the line.
- **Each card is its own box**: a border, a gap to the next, and a 4 px left edge in the card's colour —
  in this order of precedence: amber for any Decide or Do item, else teal for Waiting, else green for In
  progress, else grey. (In the mockup three
  Waiting cards ran together under a 1 px rule; the box is what Paul chose.)
- **The rows' tree is drawn**: a 2 px rule down each level's left edge in the branch's colour — green a done
  row, teal a waiting one, amber the person's, grey open. The state word stays (*after TD-875*, *waits
  until 2026-10-30*, *done #1939*): it carries the date and the PR.
- **Mentions** on a row are one phrase, *mentioned in 4 items*, deduplicated by item (TD-772 carried one
  item twice), the subjects read on hover from the data the row already has; never a line per item.
- **A Read item is one line** — who, kind, *on TD-n*, the mail's `subject` (§4.10, the first sentence to 80
  characters), age — opening on press to its body and its controls. A Decide or Do item is drawn whole: the
  kind line, the lead sentence, the consequences, *context* folded, the answers.
- **One renderer per kind, with a `card` mode.** Screen 12's sentence *drawn by the Inbox's own row
  renderers, never copies* is kept and sharpened: each kind's one renderer takes a mode, `inbox` or `card`,
  and the card mode is the shapes above — the one-line Read item, *context* for *details*, no Reply word,
  the three verbs. There is still no second renderer.

## 5. The Inbox stays, for what names no entry
On 2026-10-19 the top bar read 84 needing the person on cards and 23 in the Inbox. What stays in the Inbox
is transient or unattached — a permission prompt, a stalled session, a question about nothing in the ledger,
a team start — and has no rank to move, so it keeps its dates. The way to keep it from being a second queue
is a brief, not a gate: **a question to the person about an entry names it** — `about` already defaults to
the sender's claim (§4.10), and the briefs say to set it when the claim is not the subject. Whether a
question about work with no entry should get one filed first, and by whom (the ledger has one writer per
repo, cadence §2), is **a proposal for the read-back**, not decided here. The two-week read-back (TD-772)
then says whether what is left in the Inbox is small enough to fold into a *not on a card* line at the foot
of the Queue. Not decided before the numbers.

## 6. An item leads with one sentence
What waits on the person is written for a cold reader — *someone coming in cold (other than knowing the
basics of their project) can understand well enough to make a decision (if it is straightforward) or
start a session if discussion is actually warranted* (Paul). The shape has three parts, and **where each
part lives is fixed per kind**:

1. **One sentence** that states the decision or the task, readable with no other context: *Which Gemini
   account should the conformance walk sign in with?*; *Put the Gemini launch layer in place on this machine,
   with sudo, so a Gemini session can be launched.*
2. **What each answer leads to**, one clause each, the recommended one first and marked.
3. **Context**, folded: the ids, who did what, where it is written.

| Kind | The sentence | The consequences | The context |
|---|---|---|---|
| an `ask` or `steer` to the person | its first paragraph | its second paragraph | the rest, under *context* |
| a board line | its line, before `Context:` (cadence §3.3) — amended by §9: its bold head | `Answers:`, each `text — what it leads to`; `Recommended:` | the item's sub-bullets |
| a ledger entry that waits on the person | a new **`**Ask:**`** line **in the entry's body, beside `**Why:**` and `**Fix:**`, never in the header block** (ledgerboard validates the header field by field and rejects an undeclared one on an edited entry; `Answers:` goes in the body for the same reason) — new to cadence §2's entry shape | `**Answers:**`, each `text — what it leads to` | `**Why:**` and `**Fix:**`, as today; **an entry with no `Ask:` yet** (the backfill lands after the read-back) draws its title as the sentence and Why and Fix under *context*, as today |

**The test for one sentence is a reader of its own beside `subject_of`**, `mail.one_sentence(text)`: the
first paragraph, folded, is within `FIRST_PARA_WORDS` (60) and the subject rule's sentence pattern (§4.10: to
the first `.`, `?` or `!` followed by a space or the end) matches all of it, with inline code spans skipped
before the match. `subject_of` itself cannot be the test: it clips at `SUBJECT_CHARS` (80). An id or an
abbreviation followed by a space (*TD-909. Which…*, *e.g. this*) fails the pattern; that is a false warning,
and a warning is all it is (below). **The answers' split** is cadence §3.5's `a | b` grammar with one addition: an answer splits on its first
` — ` (space, em dash, space). **The written form is `<label> (default) — <consequence>`**: the mark is read
on the label after the split (§3.5's *ends in ` (default)`* becomes *its label ends in*), and `decided_line`
writes the mark on the label. **The split is the readers'**: `answers` on every reading — board item, ledger
entry, mail envelope — becomes the labels, with a parallel `consequences` list beside it; no writer changes,
and a press sends the index or the label as it does today, so the home's word-for-word check against
`answers` still passes. The right part is drawn as the consequence only; a reader without the card mode, a
board line or `--answer` with no dash, shows and sends the whole string as today, and a board line with no
consequence draws bare answers. That is a change to cadence §3.5 and to ledgerboard's answer readers
(`parse_answers`, `parse_default`, `answers_of`) and `decided_line` (the dev-cadence entry's). No rule on answers: an open question is legitimate (cadence §3.3: *when
only the person can know, say so and mark no default*), and Answer… is for the person's own words.

**The home warns, never refuses** — §4.10's rule stands, and this ADR does not amend it (an earlier draft
had a refusal; a refusal strands a worker that has to ask, and the home files asks of its own that no writer
could retry). An `ask` or `steer` to the person whose first paragraph fails the test gets the same one-line
warning `ao msg` prints past `FIRST_PARA_WORDS` today, with this rule's words, and sends; **the card draws a
non-conforming item with its `subject` as the sentence — the 80-character clip, which is intended — and the
whole text folded under it**, so the person always sees one line first. Home-authored rows and `--source` replies are exempt from the warning. For a
ledger entry, **the cadence check** (dev-cadence's `check_cadence.py`, the PR's cadence row) warns on a PR
that adds or edits an entry with `Owner: paul`, `decision (paul)` or `Answers:` and no `Ask:` line in its
body; for a
board line, cadence §3.3 as today. That is the whole of the enforcement: the home's warning and the card's
fold for mail, the cadence check for entries, the briefs for all four. Paul, 2026-10-19: *less desirable
would be having the techlead monitor new items added to the queue for clarity* — no seat watches.
**The rule lives in dev-cadence** (cadence §3.3 and §2's entry shape, the briefs under `docs/briefs/` and the
stage briefs), **with a backfill**: a grind job writes the `Ask:` line and the answers' consequences for every
open entry that waits on the person, as PRs the lead reads (on 2026-10-19 about 17 of shiftlead's 62 open entries, this one counted, carry `Owner: paul` or
`decision (paul)` and none an `Answers:`; the dev-cadence entry counts the other repos' at filing), **dated
from the read-back** (§8). TD-127's *one to three plain sentences* for a message's first paragraph (§4.10) is
unchanged for mail that is not to the person.

## 7. Decided with Paul (2026-10-19)
1. The Waiting group, as §1 — *it's like up next but blocked on a date*.
2. FYI and Answered for you fold by default, with counts.
3. Start session once per card, on the repo's team, with the card as context (amended, §9).
4. Decide and Do both colour the card; the backlog is large and that is fine.
5. Start session plain, not filled.
6. The pill carries counts.
7. A Waiting card's date or *event* where Up next draws the number; the full phrase at the right.
8. Each card its own box; the tree's lines, thicker than the first draft.
9. No dates of the person's on a card; the Inbox keeps them.
10. The writing rule lives in dev-cadence with a backfill, enforced mechanically, not by a seat (the
    mechanism is the warning and the fold, §6, after the review rounds: the refusal Paul was first shown
    would have broken §4.10).

## 8. Slices and the trial, for the design round to name as build entries
The design text may merge once the rounds converge. **TD-772 reads back the trial on 2026-10-30** from three
readings — passed-over flags, idle-while-work lines, the oldest unanswered TD ask (ADR 2026-10-15 §7) — and
ADR 2026-10-15 forbids a lane change before then. Nothing here changes a lane's pick, but three things change
what the readings measure, so **their builds are `Blocked by: TD-772`**: the backfill (grinder-lane time;
rewrites the entries the page shows), the §5 brief line on `about` (changes how many TD asks exist), and
the §6 warning. One more is the person's own: a Start session on a card claims an entry and takes it from
the lanes while the session lives, as a ledger row's does today; it lands now, **and it moves both
readings down**: the person's claim is in `held`, so its entry leaves `in_lanes` (an idle member beside it
samples *starved*, not *idle with work*, §4.4 *A member's own count*) and its card leaves Up next (no worker
below it is flagged for it; `_passed_over` reads Up next alone and skips every record that is not unattended).
The read-back lists the person's claims with their spans beside the two readings.
The rest change what the person sees and may land now:
- the `waits` predicate, the Waiting group with its heading *Waiting (n)*, numbering over Up next alone,
  `rank_move`'s refusal, the wait column and phrases (§1;
  the `queue` reading, `queue_part.html`, `queue_card.html`; the mockup's TD-900 card, drawn Up next with
  *after TD-904*, is Waiting under §1 with *event* in its column — the mockup was corrected, and its TD-905 row, drawn *after
  TD-904*, reads *waits on an event* as the ledger has it; its blurb's *the item you came from* under Start
  session is superseded by §3's choice by key)
- the card's three wants: the sections, the pill's and the header's counts, *Read n* on a folded card,
  *held (person)* as no want, Dismiss all per sub-section (§2)
- the three verbs: the answers row on every item, Start session on the card with its widened road, id list
  and third `why_key`, Open session only for the person's own session, the ⋯ with its keyboard model and
  §4.5a row, Delete and Pause inside it (§3)
- the box, the tree's rules, mentions deduplicated, the one-line Read item, the `card` mode of each
  renderer (§4)
- dev-cadence: the `Ask:` line in cadence §2's entry shape (a body line, nothing for ledgerboard to
  validate), the answers' ` — ` split in §3.5 and ledgerboard's reader, the briefs, the cadence check's warning, `mail.one_sentence` (§6; a dev-cadence
  entry first, then this repo's); the backfill, after TD-772
- help text and §4.5a rows for every control whose words change, the filter row's *Needs you (n)* and the
  kind pick's words among them, and display-only rows for the wait column with *would be n* and for *Read n* (bound to `help.py`: the build entry's; run `grep -ln 4.5a tests` first,
  since §4.5a rows are test keys)

## 9. Amended 2026-10-30 (TD-1066): what a board item asks, and a session on every item
Paul's TD-1033 card on 2026-10-26 showed one *Decide (1)* item, an `act` line asking him to file an entry
in another repo, and he could not tell what was asked of him. The layout was agreed with him on the
mockups of #2444 (`docs/mockups/reviews/2026-10-26-td1066-card-items.*`; his answer of 2026-10-30, *Yes*).
Design §4.5 screen 12 holds the rules; this section is what they change here.

- **An `act` line is a Do** (§2's table): cadence §3.3 gives an `act` no answers, so its answer is
  **Done**, outlined, the write-back's check-off; **Answer…** moves into its ⋯. `decide` and `look` stay
  Decide.
- **Start session on every Decide and Do item** but a red PR (§3), on the card's `start`, or on a ledger
  item's own entry, with the item as the session's subject; the header's button only on a card with no
  such item. With the person's own session on the card each item's button reads **Open session**, goes
  there and puts the item's id on the clipboard; the page types nothing into a session the person drives.
- **The id list names the items**: *waits on me* carries every Decide and Do item by its id
  (`board:<key>`, `m-…`, `<repo>#TD-n`, a red PR's `<repo>#<n>`), ids only as before; the session reads each itself.
- **A board item leads with its task** (§6's table): its bold head is the sentence, *in <repo>* on its
  kind line where its `Context:` names another repo, its prefix and key under *context*, and its
  *standing* in Answer…'s `title`, not its head.
- **No footer** on a card's board item: its write-back words are Done's `title`.
- **A line found done closes in a PR of its own** where no open PR of the session's does its task, never
  folded into a PR that does other work (design §4.9a).
  *Closing in #n*, read from an open PR's description, was left out: the close in its own PR makes it
  rarely needed.

## Review record
Round 1 (2026-10-19, Fable and Sonnet in parallel, both NOT READY, 16 and 12 findings; adopted into this
text as one pass): Waiting as a `waits` predicate read before any need, the column's fallback order and
*blocked* kept as a word, numbering over Up next alone and *would be n*, the widened Start session road with
its claim owned and a third `why_key`, the header button carrying the one Do item, Open session only for the
person's own session, the full map of sections and controls (running steer, board kinds, *held (person)*,
Delete, Pause, Dismiss all, *Read n* on a folded card), one renderer per kind with a `card` mode, the counts
display only, the writing rule's fields per kind and `subject_of` as its test, the refusal dropped for §4.10's
warning and the card's fold, §5 made a brief and a proposal, the builds that touch the trial's readings
blocked by TD-772. Not adopted: Sonnet's *latest* `until` for the column (the earliest is when anything on
the card can be picked). From round 2 the rounds alternate, Sonnet then Fable, with a fix between each.
Round 2 (Sonnet, NOT READY, 9 findings; adopted): `Ask:` in the entry's body, never the header block
(ledgerboard rejects an undeclared header field); `mail.one_sentence` as the test, since `subject_of` clips
at 80; a child blocked only by the person's own entry is not a wait; `waits` reads `unreachable` and
`NO_LANE` itself and counts a *held (person)* entry as the person's own; the road's checks in place of
*for you*, a deterministic choice, 409 on a worker's hold; *card* for every entry that is not the person's;
the event phrase's member; the widened road lands now with its reason; the backfill count corrected.
Round 3 (Fable, NOT READY, nothing blocking, 10 findings; adopted): a member blocked by the Do and by TD-x
waits on TD-x; a row of the person's keeps its need over *held by*; Open session wins over a worker's hold and
the road goes there before it starts; the red PR row is a Do item; Overrule, Send to reviewer and a decided
line's Done placed; a held card reads *held (person)*, never *ready*; the widened road moves both readings
down, said so; `start` on each card of the reading; display-only §4.5a rows named.
Round 4 (Sonnet, NOT READY, no contradictions, 12 decisions left to a builder; adopted): the answers' ` — `
split and its cadence §3.5 / ledgerboard change; the red PR row's count and card; the column and phrase from
a leaf, *not live* added (not adopted: *after TD-n* as a column word — a member waiting only on open ids is
never a leaf); the header's ⋯ acts on the top entry; the pill beside a Waiting card's phrase and the edge's
precedence; the person's own session defined, several sessions ordered; an entry with no `Ask:` yet draws
its title; the *card* prompt's words and the id list's format; the claim is the tick's derived one, a hold
stays; `rank_move` refuses Waiting; *Waiting (n)* in §8.
Round 5 (Fable, NOT READY, nothing blocking, no contradiction, 6 findings; adopted): a cycle with no leaf
reads *blocked* from its lowest-keyed member; the answers' written form `<label> (default) — <consequence>`,
the split the readers' (`answers` the labels, `consequences` beside) with no writer changed, the readers
named; one `work.md` template reshaped by key with the id list for every key and today's closing sentences
kept; a held Waiting card starts on the card's chosen entry; the two design sentences on a held card moving
and `rank.intent`'s words listed; §4.4 *Hold* gains the derived-claim sentence.
Round 6 (Sonnet): **READY** — the six round-5 adoptions match the code and the design; one nit adopted, the
id list says *none* for an empty group. Converged 2026-10-19: six rounds, three each, alternating from
round 2 with a fix between each.
