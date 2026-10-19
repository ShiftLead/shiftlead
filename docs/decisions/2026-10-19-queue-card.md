# ADR 2026-10-19: The Queue card — three wants, three verbs, a Waiting group, items that lead with one sentence

Status: **proposed, held** — drawn with Paul on 2026-10-19 over an afternoon of rounds on two review
pages built from the live ledger ([the card](../mockups/reviews/2026-10-19-queue-card.html),
[the page](../mockups/reviews/2026-10-19-queue-redesign.html), its shot
[`2026-10-19-queue-redesign.png`](../mockups/reviews/2026-10-19-queue-redesign.png)). TD-909 carries it; its
`Blocked by: decision (paul)` stands until the Fable and Sonnet rounds below converge, then the designer's
round writes it into §4.4 *The Queue: cards, and the rank that orders them*, §4.5 screen 12 and §4.5a, and the
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
The Queue was built (TD-769–TD-771, merged 2026-10-16) and measured on 2026-10-19 with the live ledger: 197
cards Up next, 82 of them amber, 11 reading only *waiting*, the tallest card 3,212 px (TD-900: seven
*Answered for you* items drawn in the Inbox's full shape above its six rows), the median 138 px. Card 1 was
TD-748 itself, waiting on a date eleven days out and saying only *waiting*, headed by an FYI about a row
already done. The card has the right content and the wrong grammar: a dozen words for what it wants from
the person, a dozen controls whose meaning depends on a kind the person cannot see, and text written for
the writer.

## 1. Groups: Waiting, between In progress and Up next
The page has four groups, furthest through first: **Recently completed**, **In progress**, **Waiting**,
**Up next**. Waiting holds every open card nobody can pick: the ledger's part of the card's status is
*waiting* or *blocked* (§4.4 *The card's status*) — every open member has a `Waits:` line, is a live check
whose build is not live, is blocked only by open ids, is settling, or is blocked past the org's reach. A
card with a Decide or Do item (§2) is **still in Waiting** when the ledger says it waits: the group says
where the work is, the colour says whether the person is in it. Waiting cards are not numbered; the
card's place in Up next is kept (the rank is untouched; the group is a view) and the card says so, *keeps
place 1*. Where Up next draws the number, a Waiting card draws its date, *Oct 30*, or the word *event*, at
the same size and strength, with the repo chip under it as a number has; its status at the right is the
whole phrase, *waits until Oct 30*, *waits on the next launch whose first hook is lost*, *after
dev-cadence#TD-119*, *decision (techlead)*. The status *blocked* folds into Waiting as one of the reasons
and is no longer a group of its own or a distinct word on the card: a blocker past the org's reach reads as
what it is. Up next is then exactly what is pickable now or needs the person. The pick order lanes read is
unchanged; TD-772's read-back counts the group as a change to what the person sees, not to any lane.

## 2. Three wants
A card can want three things of the person, and the section names say which:

| Want | What it is today | Where it is drawn |
|---|---|---|
| **Decide** | an `ask` with answers, a `steer`, a board line, a `Blocked by: decision (paul)` hold, an entry with `Answers:` | the header, open, amber |
| **Do** | an entry whose `Owner:` is the person (*yours to do*) | the header, open, amber |
| **Read** | FYI (notes, the trail) and *Answered for you* | under the rows, **folded with its count** |

Decide and Do both colour the card amber and both are counted on its pill, *Decide 1 · Do 1*; the page
header counts them across the Queue, *Decide 12 · Do 70*. Paul, 2026-10-19: *Do and Decide coloring a card
is good — it lets me know what is waiting on me. We have a large backlog currently, and that's ok.* Read is
never counted and never colours. *Answered for you* stays its own line inside Read's fold, *Read (7) —
answered for you*, because it exists so a confident wrong answer cannot steer a team unseen: folded with a
count keeps that; folded without one would lose it. Steering (a paused `steer`) is a Decide item.
The Inbox's five section names and renderers stand on the Inbox (§4.5 screen 6); the card maps them to
these three.

## 3. Three verbs
Whatever the item's kind, the person does one of three things, and the words are the same on every item:

- **Answer** — the item's answers drawn as buttons, the recommended one outlined (no caption: the outline
  is the convention), and **Answer…** for the person's own words. *Done* on a Do item, *Lift the hold* on a
  hold, *Go with it* on a steer and *Works* on a look are answers, drawn in this row, each taking the road
  its kind already has (§4.4 *Board write-back*, §4.5a *Inbox row: ledger entry*). No **Reply** word on a
  card: a reply on a ledger row is a work order, not a conversation, and the word hid that.
- **Start session** — **once per card, in its header**, plain (a filled button was too loud; Paul,
  2026-10-19). It is the Do verb: *if I have a "Do" item I am going to start a session and have the AI do as
  much of it as possible, giving me easy copy/paste or instructions for the rest.* **It starts the person's
  own interactive session on the card's repo's team, with the card as its context**: the existing ledger-row
  rule (§4.5 screen 6 *The ledger's entries that wait on you*, §4.5a *Inbox row: ledger entry: Start
  session*: on the repo's team, in a worktree `td-<n>` of the top entry, its fixed opening prompt sent, its
  Focus opened, or the New session form filled in where it cannot be silent) applied to the top entry, with
  the opening prompt naming the card's entries and the item the person came from when they pressed from one
  (the Do item's entry, the Decide item's question). A card whose members span repos starts on the top
  entry's repo's team and names the rest. While a live record holds the top entry it reads **Open session**
  and goes there. One session per card, since the session will want the whole card anyway.
- **⋯** — the team's controls, behind one visible mark: **Hold** (*keep the team off this*, the one
  "not now" that survives on a card, because it stops a lane and is not about the person), **Back to
  design…**, **Done…** on an entry, **Open** on the Repo page (§4.5 screen 12 *any open row*). They are drawn
  on hover or focus of a header or row and the ⋯ is always there for the keyboard.

**No dates of the person's on a card.** No Snooze, no Put on the board, no Due. The rank is the snooze: a
card not wanted now moves down. Waiting is the ledger's own dates. The Inbox keeps Snooze, Put on the board
and `Due:` for what names no entry (§5).

## 4. The header and the rows
- **The header's right edge** reads, in order: the move arrows, Start session and ⋯, a gap, then the facts —
  *n entries* and one status. The status ends the line. On an Up next card the status is the ledger's word
  or the amber pill with its counts; on a Waiting card the wait phrase; on an In progress card *d/m done*
  beside *in review #n*.
- **Each card is its own box**: a border, a gap to the next, and a 4 px left edge in the card's colour —
  amber for Decide or Do, teal for Waiting, green for In progress, grey otherwise. Three cards in Waiting ran
  together under the 1 px rule.
- **The rows' tree is drawn**: a 2 px rule down each level's left edge in the branch's colour — green a done
  row, teal a waiting one, amber the person's, grey open. The state word stays (*after TD-875*, *waits
  until 2026-10-30*, *done #1939*): it carries the date and the PR.
- **Mentions** on a row are one phrase, *mentioned in 4 items*, deduplicated by item (TD-772 carried one
  item twice), the subjects on hover; never a line per item.
- **A Read item is one line** — who, kind, *on TD-n*, the lead sentence, age — opening on press to its
  body and its controls (Dismiss, Put on the board — the Inbox's, unchanged). A Decide or Do item is drawn
  whole: the kind line, the lead sentence, the consequences, *context* folded, the answers.

## 5. The Inbox stays, for what names no entry
On 2026-10-19 the top bar read 84 needing the person on cards and 23 in the Inbox. What stays in the Inbox
is transient or unattached — a permission prompt, a stalled session, a question about nothing in the ledger,
a team start — and has no rank to move, so it keeps its dates. The way to keep it from being a second queue
is a rule, not a group: **a question to the person that could name an entry names one** (`about`, §4.10),
and a question about work with no entry files one first (the asker's, or the groom's). The two-week
read-back (TD-772) then says whether what is left is small enough to fold into a *not on a card* line at
the foot of the Queue. Not decided before the numbers.

## 6. An item leads with one sentence
What waits on the person is written for a cold reader — *someone coming in cold (other than knowing the
basics of their project) can understand well enough to make a decision (if it is straightforward) or
start a session if discussion is actually warranted* (Paul). The shape, for every `ask` to the person,
every `steer`, every board line, and every ledger entry whose `Owner:` is the person or whose `Blocked by:`
holds `decision (paul)`:

1. **One sentence** that states the decision or the task, readable with no other context: *Which Gemini
   account should the conformance walk sign in with?*; *Put the Gemini launch layer in place on this machine,
   with sudo, so a Gemini session can be launched.*
2. **What each answer leads to**, one clause each, the recommended one first and marked.
3. **Context**, folded: the ids, who did what, where it is written.

Cadence §3.3 (*An item explains itself*: `Context:`, `Question:`, `Caveats:`, `Recommended:`) already asks
this of a board item; the rule extends it to the ask, the steer and the ledger entry that waits on the
person, in dev-cadence (its cadence text and the briefs under `docs/briefs/`, the stage briefs), **with a
backfill**: a grind job rewrites the `Why`/`Fix` lead of every open entry that waits on the person into the
shape, as PRs the lead reads (about 60 entries on 2026-10-19). **Enforcement is mechanical**, not a seat
watching: the home refuses an `ask` to the person whose first paragraph is not one sentence or that carries
no answers, as it warns on a steer past ~100 words today (§4.10), and returns it to the asker with the rule.
Paul, 2026-10-19: *less desirable would be having the techlead monitor new items added to the queue for
clarity.* A writer that cannot state the question in a sentence does not understand it well enough to ask.

## 7. Decided with Paul (2026-10-19)
1. The Waiting group, as §1 — *it's like up next but blocked on a date*.
2. FYI and Answered for you fold by default, with counts.
3. Start session once per card, on the repo's team, with the card as context.
4. Decide and Do both colour the card; the backlog is large and that is fine.
5. Start session plain, not filled.
6. The pill carries counts.
7. A Waiting card's date or *event* where Up next draws the number; the full phrase at the right.
8. Each card its own box; the tree's lines, thicker than the first draft.
9. No dates of the person's on a card; the Inbox keeps them.
10. The writing rule lives in dev-cadence with a backfill, enforced by the home, not by a seat.

## 8. Slices, for the design round to name as build entries
- the Waiting group and the card's wait column (§1; the `queue` reading's groups, `queue_part.html`, `queue_card.html`)
- the card's sections renamed and folded, the pill's counts, the page header's counts (§2)
- the three verbs on an item, Start session on the card with its context, the ⋯ (§3; `queue_row.html`, the
  ledger row's and mail row's renderers, the New session road)
- the box, the tree's rules, mentions deduplicated, the one-line Read item (§4)
- dev-cadence: the writing rule in cadence §3.3's shape for asks, steers and entries that wait on the person;
  the home's refusal; the backfill (§6; a dev-cadence entry first, then this repo's)
- help text and §4.5a rows for every control whose words change (bound to `help.py`: the build entry's)

## Review record
To be filled by the Fable and Sonnet rounds on this text; TD-909 holds until they converge.
