# Review record: TD-1557

**Design:** docs/design/4.4-host-agent.md *Decide*; docs/design/4.5-ui.md screen 6 rule 4 and screen 12 *Three verbs: Answer*; docs/design/4.5a-controls.md (row *Due strip / Inbox board row: a slot answer* and the rows it touches); docs/design/4.10-messages.md; docs/glossary.md *slot answer*
**Builds:** TD-9001, TD-9002
**Class:** wide
**Decided:** pending — the rounds ended at the cap (round 6, wide, cap 6) with one build-changing fix no review has read (F101), and the minor F102–F104 after it (the closing fact-check's own minor fixes, F105–F111, read by its re-runs); the end-of-rounds item recommends One more round
- Decided: no steer and no ask was sent during the rounds: every finding followed from what was written, and was applied (F88 rejected, its reason in its row).
- Decided: the end-of-rounds item, which would have been added to docs/user_attention.md by `board_edit.py add --kind decide --context "TD-1557 decision (paul)" --parts TD-9001,TD-9002 --due 2026-11-16 --no-commit` and committed here, is: *Should TD-1557's builds (a Hold: <note> answer filled from your words, and Answer… on a board item that decides when its words are one of its answers) go ahead after six review rounds ended at the cap, one build-changing fix unread by any review? Context: TD-1557 decision (paul). Parts: TD-9001, TD-9002. Due: 2026-11-16. Answers: One more round (default) \| Go \| Hold: <note>.* Its detail block: the rounds ended at the cap; build-changing per round in the design reviews 10, 4, 1, 1, 3, 1 (the fact-checks' 1, 1, 0, 0, 1, 0); unread by a review, by build — TD-9002: F101 (the box bound to Answer… carries whether the line is open and undecided; a decided or closed line binds no answers); recurring topics, each with *is this the wrong design?* — the kept words of a refused box (F37, F66, F82: now kept with the road of the box they were typed in), the page's reading of Answer… (F9, F19, F30, F46, F60: four comparisons against the server's lists, the agent the one filler), the form as a default (F1, F35; F22, F45: a form may be recommended, never taken without words), and the agent's second check (F21, F81: it guards a handed answers list, a changed line meeting its key's refusal first); recommendation: One more round, for F101.
- Decided: with the item, TD-1557, TD-9001 and TD-9002 each carry `**Blocked by:** decision (paul)` and an `**Ask:**` line (TD-9001 keeping its event gate beside it).
- Decided: the ask to ledgerboard's question seat, which would have been sent by `ao td add --repo ledgerboard`, is: *A board answer that is a form, `<label>: <slot>` (Hold: <note>), filled from the person's words: add `slot_label(answer)` and `fill_slot(said, offered)` as shiftlead's TD-9001 Fix states them (grammar, trimmed label ignoring case, the first offered form, refusals, Not right's wider placeholder), keep `is_not_right_form`, no writer change.* The ask to agent-cadence's seat, by `ao td add --repo agent-cadence`: *vendor the ledgerboard release that carries `fill_slot`, once ledgerboard tags it, so shiftlead's TD-9001 pin bump can bring it.*
- Decided: the fact-check trial's ask to `fact-check-ao-1`, which would have been sent once the design PR's head was pushed (outside the gate, no row, no line), and its one `fact-check-trial:` comment, are not sent.
- Decided: no design PR was opened (the replay opens none), so the entry's `Design PR:` section is not written.
- Decided: replay ended — cap (round 6 of the wide class's 6 raised a build-changing finding, F101; the closing fact-check's re-run R21 raised nothing).
**Source:** rounds

| review | round | role | model | tokens | date |
|---|---|---|---|---|---|
| R1 | 1 | fact-check | sonnet? | 75998 | 2026-11-13 |
| R2 | 1 | design | fable? | 137039 | 2026-11-13 |
| R3 | 1 | design | sonnet? | 115032 | 2026-11-13 |
| R4 | 2 | fact-check | sonnet? | 104122 | 2026-11-13 |
| R5 | 2 | design | fable? | 119891 | 2026-11-13 |
| R6 | 2 | design | sonnet? | 103499 | 2026-11-13 |
| R7 | 3 | fact-check | sonnet? | 67580 | 2026-11-13 |
| R8 | 3 | design | fable? | 159716 | 2026-11-13 |
| R9 | 3 | design | sonnet? | 86075 | 2026-11-13 |
| R10 | 4 | fact-check | sonnet? | 55408 | 2026-11-13 |
| R11 | 4 | design | fable? | 194032 | 2026-11-13 |
| R12 | 4 | design | sonnet? | 104289 | 2026-11-13 |
| R13 | 5 | fact-check | sonnet? | 60588 | 2026-11-13 |
| R14 | 5 | design | fable? | 143349 | 2026-11-13 |
| R15 | 5 | design | sonnet? | 161702 | 2026-11-13 |
| R16 | 6 | fact-check | sonnet? | 55120 | 2026-11-13 |
| R17 | 6 | design | fable? | 171968 | 2026-11-13 |
| R18 | 6 | design | sonnet? | 107864 | 2026-11-13 |
| R19 | 6 | fact-check (closing) | sonnet? | 81218 | 2026-11-13 |
| R20 | 6 | fact-check (closing, re-run) | sonnet? | 52524 | 2026-11-13 |
| R21 | 6 | fact-check (closing, re-run) | sonnet? | 40444 | 2026-11-13 |

| id | round | by | topic | mechanism | finding | class | status |
|---|---|---|---|---|---|---|---|
| F1 | 1 | R1 | form default | ledgerboard's writer | TD-9001's Done when is vacuous: the writer already refuses a typed ` (default)`; the default is an index, so the check must name an index on a form | build-changing | applied |
| F2 | 1 | R1 | form default | the home's send | the mail default check and the ` (default)` mark (`answer_mark`) before `slot_label` were undeclared and unsaid | minor | applied |
| F3 | 1 | R1 | ledgerboard names | `is_not_right_form` | §4.4 said the new names take the old ones' place while TD-9001 keeps them; the look's pair still reads them | minor | applied |
| F4 | 1 | R1 | form button | wire names | the board form button's wire name was unnamed; `board_slot` named, ledger and mail rows' named, the begun-prefix rule generalised | minor | applied |
| F5 | 1 | R1 | form reading | the reader's answers | a board line's answer is its whole string, not a split label | minor | applied |
| F6 | 1 | R2 | form reading | the reader's answers | reopens F5: a board line's answers are already `parse_answers`' labels, mark and consequence removed; the text said its whole string | build-changing | applied |
| F7 | 1 | R2 | ledger road | `rpc_ledger_decide` | the ledger road could still write `Hold: <note>` (an index or `go`) and wrote unfilled words; its check and its default on a form were unsaid | build-changing | applied |
| F8 | 1 | R2 | look hand-off | `board_notright` | Answer… filling a look's *Not right* did not say whether it hands off; it takes Not right…'s road, `board_answer` carrying head and repo | build-changing | applied |
| F9 | 1 | R2 | Answer… reading | the page's reading | the order (word for word, fill, label with no words, Reply) and the form as written were unsaid, and the page would re-parse the grammar; it reads only the reader's `answers` and `forms` | build-changing | applied |
| F10 | 1 | R2 | form button | `board_slot` | on a card it was unsaid whether Hold… is `board_slot` or Answer…'s box; it is `board_slot`, always a decide | build-changing | applied |
| F11 | 1 | R2 | mail entry points | the home's send | a pick of a form's index and a `--recommend` that is a form were unguarded | minor | applied |
| F12 | 1 | R2 | begun prefix | the composer | a retyped label stripped with an optional colon would rewrite *hold off* as `Hold: off`; strip only with its colon | minor | applied |
| F13 | 1 | R2 | bound box | TD-1555's binding | the answers the reading uses were not among the bound fields | minor | applied |
| F14 | 1 | R2 | open line | a decided line | "open line" took in a decided line, which refuses a second decide; open, undecided | minor | applied |
| F15 | 1 | R2 | entry points | the page | TD-9002 did not list the ask row, the ledger row, the Go with it sites or app.js's frame lists | minor | applied |
| F16 | 1 | R2 | decide lift | the Log | a filled form's `kept waiting` Log line, with the person's words, on the entry and each part was unsaid | minor | applied |
| F17 | 1 | R2 | form grammar | `slot_label` | an autolink answer read as a form and `Not right:<what>` lost; the placeholder holds no `:` or `/`, any space after the colon | minor | applied |
| F18 | 1 | R2 | TD-9001 Done when | the probe | the probe could be refused for a missing context before the form check | minor | applied |
| F19 | 1 | R3 | Answer… reading | the page's reading | reopens F9: the page must compare as it types, so "parses no grammar" could not hold; four comparisons against the reader's lists, the `<…>` test the agent's alone | build-changing | applied |
| F20 | 1 | R3 | form button | `board_slot` | whether the box sends its text as typed or label plus stripped words was unsaid; as typed, `fill_slot` the one filler, Send off while no fill | build-changing | applied |
| F21 | 1 | R3 | agent check | `write_back` | the agent checked only the page's `answers`; it checks the line's own `Answers:` as the write finds it | build-changing | applied |
| F22 | 1 | R3 | form default | a steer's lapse | an open steer whose default is a form would lapse to the placeholder; its lapse note says no answer was taken | build-changing | applied |
| F23 | 1 | R3 | press frame | the pending mark | Answer…'s frame was keyed by its button (`board_reply`); it is chosen on Send by the road the words take | build-changing | applied |
| F24 | 1 | R3 | form reading | `ledger.answers_of` | a ledger entry's answers are `ledger.answers_of`'s, not `parse_answers`' | minor | applied |
| F25 | 1 | R3 | form default | the home's send | a steer's default is one cleaned line: split, mark, then `slot_label` | minor | applied |
| F26 | 1 | R3 | bound box | TD-1555's binding | whether the item is a look's pair was not bound | minor | applied |
| F27 | 1 | R3 | mail form | the composer | a mail row's Hold… had no Send rule; Send off on every row with no words | minor | applied |
| F28 | 1 | R3 | wording | §4.5a rows | "an answer of its line" left out the filled form in three places | minor | applied |
| F29 | 1 | R3 | case | the page's reading | word for word counts case while a label does not; said on purpose | minor | applied |
| F30 | 2 | R4 | Answer… reading | the page's reading | `Hold: <b>` was read two ways in screen 12 (*needs its words* and *decides*); the page's *neither* is a bare label or the form as offered | build-changing | applied |
| F31 | 2 | R4 | ledgerboard names | `fill_not_right` | the look's pair calls only `is_not_right_form`; `fill_not_right`'s one caller moves to `fill_slot` | minor | applied |
| F32 | 2 | R4 | lapse note | `_lapse_or_expire` | the lapse note is `agent_inbox.py`'s, in two wordings | minor | applied |
| F33 | 2 | R4 | ledger road | the check | "as the write finds it on origin" was said of the ledger road, which has no found line | minor | applied |
| F34 | 2 | R4 | prep file | undeclared claims | `drawn`, `named`, `boardgo`, the pair's head and repo, the Log line were undeclared | minor | applied |
| F35 | 2 | R5 | form default | ledgerboard's writer | reopens F1: the writer's refusal of a form default broke cadence §4.8, whose end-of-rounds item may recommend `Hold: <note>`; a form is now never *taken* as a default — marked and outlined, no Go with it, no writer change | build-changing | applied |
| F36 | 2 | R5 | agent check | the applying mark | follows F21: whether the page-list check refuses, and which fill the mark and subject carry, were unsaid; two checks, the first's fill carried | minor | applied |
| F37 | 2 | R5 | refused decide | kept words | Hold…'s box and Answer… kept a refused decide's words differently; one rule, by `board:<key>`, kept words over a begun label | minor | applied |
| F38 | 2 | R5 | decide lift | the Log | an event gate writes no Log line; the Log line is a `decision` gate's | minor | applied |
| F39 | 2 | R5 | form reading | `ledger.answers_of` | TD-9002's reader bullet still named `parse_answers` for a ledger entry, and where `forms` is computed was unsaid | minor | applied |
| F40 | 2 | R5 | form default | `inbox_go_with_it` | follows F22: the Go with it RPC was unguarded for an old form-default steer | minor | applied |
| F41 | 2 | R5 | mail reply | the home's reply | the glossary's "sent with no words is refused" was false on the mail road; the home refuses a reply that is a bare form | minor | applied |
| F42 | 2 | R5 | pending mark | §4.5a's row | the pending row's board decide list was not widened with the form and Answer… | minor | applied |
| F43 | 2 | R5 | Answer… reading | wording | reopens F30: the order still said "not a lone placeholder"; "with any words after it" | minor | applied |
| F44 | 2 | R5 | form grammar | `slot_label` | trimming before the label compare, an empty placeholder, `is_not_right_form` narrowing, and what is drawn on the press were unsaid | minor | applied |
| F45 | 2 | R6 | form default | a steer's lapse | reopens F22: the lapse note's rewrite left five readers and rule 8's work saying the old thing; dropped — an old form-default steer lapses as any, its default the sender's own plan | build-changing | applied |
| F46 | 2 | R6 | Answer… reading | the label compare | the page's compare ("begins with the label and its colon") parted from `fill_slot`'s trimmed part before the first colon; one wording in all three places | build-changing | applied |
| F47 | 2 | R6 | mail roads | the orphan branch | the refusals had two places to live (the orphan's pick check returns first) and no sender scope; before the orphan return, from any sender | build-changing | applied |
| F48 | 2 | R6 | mail fill | the reply | a mail reply is sent as typed, so "as offered" was false for it | minor | applied |
| F49 | 2 | R6 | Answer… on ledger and mail | the box | Answer… on a ledger or mail item had no line and no kept-words rule; none, its own bound key | minor | applied |
| F50 | 2 | R6 | form grammar | `slot_label` | an empty label was a form, and the look pair's form vs `slot_label`; label not empty, the pair is cadence's fixed form | minor | applied |
| F51 | 2 | R6 | decide lift | `Lifts:` | a form named in `Lifts:` never lifts and nothing said so | minor | applied |
| F52 | 3 | R7 | form grammar | §4.5a's row | the row left out the empty placeholder that §4.4 and TD-9001 allow | minor | applied |
| F53 | 3 | R8 | ledger row | rule 4 | a ledger row's fill "drawn on the press" had no row to draw on; board line only, the ledger row's toast | minor | applied |
| F54 | 3 | R8 | mail reply | the home's reply | the bare-form reply's compare was unsaid; `fill_slot`'s refusal on the whole text | minor | applied |
| F55 | 3 | R8 | form button | `board_slot` | "that form's decide" vs any form's label; the first offered whose label the words name, the message naming the pressed form's | minor | applied |
| F56 | 3 | R8 | act line | `_board_answer` | the `act` line's fixed *have a session do it* was not exempt from the checks | minor | applied |
| F57 | 3 | R8 | form grammar | `fill_slot` | which placeholder a lone `<…>` refusal reads was unsaid; any `<…>` with no `<` or `>` inside | minor | applied |
| F58 | 3 | R8 | upstream ask | TD-9001's event | who asks ledgerboard's seat was unowned; the designer at the end of the rounds, the Status naming it | minor | applied |
| F59 | 3 | R8 | loose ends | the page | where a board item's `forms` is computed, `board_slot`'s `named` entry, which box takes kept words, the ask row's pointer (the ledger row named by the slot row, its own text left as it was) | minor | applied |
| F60 | 3 | R9 | form fill | `fill_slot` | reopens F46 and F57: words with no colon had no reading (`Hold` alone a Reply, a refusal or a decision); no colon names no form, `fill_slot` None | build-changing | applied |
| F61 | 3 | R9 | case fold | the label compare | the page's and the agent's case folds could part on non-ASCII; `str.lower()` and `toLowerCase()` named | minor | applied |
| F62 | 3 | R9 | decide lift | `Lifts:` | a form in `Lifts:` passes ledgerboard's check and never lifts; accepted and inert, said | minor | applied |
| F63 | 3 | R9 | TD-9001 Done when | the probes | the grammar's edges had no acceptance probe; `slot_label` probes added | minor | applied |
| F64 | 4 | R10 | wording | §4.4 | the `act` line's exception was spliced in with a stray `—:` | minor | applied |
| F65 | 4 | R10 | form reading | `board_rows` | the board item's `forms` is computed in `inbox.board_rows`, the rows a Queue card draws too | minor | applied |
| F66 | 4 | R11 | kept words | `AO.keptWords` | follows F37: an Inbox or Repo row has no Answer…, so a refused form's words had no box, or came back in Reply and decided nothing; a form's box takes them when they begin with its label, never a row's Reply, the toast naming the page's box | build-changing | applied |
| F67 | 4 | R11 | help text | `help.py` | the help paragraphs for a board row's answers and the card's Answer… went stale; TD-9002 amends them with `help.py` (held word for word by `tests/test_help.py`) | minor | applied |
| F68 | 4 | R11 | sibling rows | §4.5a, §4.10 | the suggested-answers, steer and orphan rows and §4.10's whole-string sentence did not point at the form rule; the orphan row's Go with it was not listed | minor | applied |
| F69 | 4 | R11 | upstream ask | agent-cadence's vendor | follows F58: nobody asked agent-cadence to vendor the release; the designer asks both seats | minor | applied |
| F70 | 4 | R11 | refusal words | the mail roads | the mail refusals had no words and TD-9002's Location was short; one sentence, Location completed | minor | applied |
| F71 | 4 | R12 | keys | §4.5a's keys row | `g` and `1`–`4` were not widened for a form default and a form's box | minor | applied |
| F72 | 4 | R12 | CLI | `_answer_lines` | `ao inbox` and `ao repo` print a form as a numbered pick the home refuses; printed as written with its reply hint, `cli.py` in the Location | minor | applied |
| F73 | 4 | R12 | ledger road | `rpc_ledger_decide` | TD-9002 named `answers_of` where the road reads the home's view, and left out "that is no form" | minor | applied |
| F74 | 4 | R12 | Answer… reading | the exact compare | `hold: <note>` read two ways; the form-as-offered compare is exact, the agent refusing the rest | minor | applied |
| F75 | 4 | R12 | whitespace | the collapse | Python's and JS's whitespace differ on control characters; both named, a mismatch the agent's refusal | minor | applied |
| F76 | 4 | R12 | kept words | the store | whether kept words outlive a box that does not take them was unsaid; kept until a box takes them or the row's next press | minor | applied |
| F77 | 4 | R12 | form sites | the Repo page | the slot row's sites left out the Repo page's board rows | minor | applied |
| F78 | 4 | R12 | form default | an old steer | "never taken as a default" read as absolute beside the old steer's lapse; the exception named in the sentence | minor | applied |
| F79 | 5 | R13 | CLI | `ao inbox`'s loop | follows F72: `_answer_lines` prints no pick number and `ao inbox` numbers answers in its own loop; both sites named | build-changing | applied |
| F80 | 5 | R13 | refusal words | `board.MOVED` | TD-9002 quoted a refusal that does not exist; `board.MOVED` named | minor | applied |
| F81 | 5 | R14 | agent check | `item_key` | reopens F80 (and F21, F36): a changed `Answers:` changes the line's key, so a keyed press meets `NO_LINE`, not `MOVED`; the second check guards a handed `answers` that is not the line's; the test and the kept words of a reworded line restated | build-changing | applied |
| F82 | 5 | R14 | kept words | `AO.keptWords` | follows F66 and F76: one store held a Reply's and a decide's words, and "never a row's Reply" stranded TD-1555's Reply words; kept words carry their road, the toast naming the opening button | build-changing | applied |
| F83 | 5 | R14 | kept words | the label compare | follows F46: "begin with its label and colon" parted from the fill test; the same wording | minor | applied |
| F84 | 5 | R14 | form default | `inbox_go_with_it` | follows F40 and F47: the check's place before the orphaned-steer branch was unsaid | minor | applied |
| F85 | 5 | R14 | form reading | `mail.read_answers` | the mail item's `forms` and the CLI sites' source were unnamed; `read_answers`, `slot_label` where no `forms` | minor | applied |
| F86 | 5 | R14 | refusal words | `fill_slot` | whether *Not right needs its words* is the look's or the label's was unsaid; the label's, on any line | minor | applied |
| F87 | 5 | R15 | decide lift | the ledger road | the `kept waiting` Log line was said of both roads; only the board decide passes the ledger to `plan_edit`, the ledger road's filled form a decided line with no Log | build-changing | applied |
| F88 | 5 | R15 | help text | §4.5a *The help text* | the design's help paragraphs say the old rule and **<label>…** has none | minor | rejected: `tests/test_help.py` holds the design's paragraphs and `help.py` word for word, so changing them here would leave main red until the build; TD-9002 carries the exact words, and the form's new paragraph, to change both in its PR |
| F89 | 5 | R15 | form reading | `ANSWER_CAP` | a mail form longer than 80 characters lost its `>` to the cap; `slot_label` reads the label before the cap | minor | applied |
| F90 | 5 | R15 | whitespace | the page's collapse | `.split(/\s+/)` without a trim; `s.trim().split(/\s+/).join(" ")` | minor | applied |
| F91 | 5 | R15 | act line | the first check | the first check cannot see an `act` line; it passes the fixed text by and the second refuses it unless the line is an `act` | minor | applied |
| F92 | 5 | R15 | look pair | `slot_label` | a pair with an odd placeholder was a pair but no form; for `Not right`, `slot_label` takes the pair test's placeholder | minor | applied |
| F93 | 5 | R15 | loose ends | toast, CLI, steer default | a card's form box had no toast words, the CLI's other numbers, a new steer default of a bare label | minor | applied |
| F94 | 6 | R16 | CLI | the echoes | follows F79: `ao msg`'s send and pass-up echoes also number answers; four sites named | minor | applied |
| F95 | 6 | R17 | kept words | the box's road | follows F82: a re-read closes a box before Send; the road is the box's, a card's Answer… on an answerable line and a form's box deciding | minor | applied |
| F96 | 6 | R17 | kept words | when they drop | follows F76: "the row's next press" was undefined; a press sent, not a box opened | minor | applied |
| F97 | 6 | R17 | kept words | a reworded line | follows F81: words kept under a key no box opens were lost; not kept, put on the error line to copy | minor | applied |
| F98 | 6 | R17 | form reading | the uncapped split | follows F89: `split_answer` caps itself; one uncapped split, as `ledger.answers_of`'s, at every site | minor | applied |
| F99 | 6 | R17 | refusal words | a steer's default | follows F70: the default's refusal told its sender to reply; a sentence of its own | minor | applied |
| F100 | 6 | R17 | keys | `g` on a steer row | follows F71: the qualifier bound only the board row | minor | applied |
| F101 | 6 | R18 | bound box | the line's state | reopens F13 and F26: the bound fields left out whether the line is open and undecided, so a decided line's kept `answers` read typed words as a decide; bound, a decided or closed line binding no `answers` | build-changing | applied |
| F102 | 6 | R18 | CLI | §4.10 | the CLI's unnumbered form was in TD-9002 alone; §4.10 says it | minor | applied |
| F103 | 6 | R18 | keys | `g` | reopens F100: the qualifier still bound the board row alone | minor | applied |
| F104 | 6 | R18 | glossary | *slot answer* | "pressed with no words is refused" read as the press erroring; a form sent with no words | minor | applied |
| F105 | 6 | R19 | prep file | the `press` guard | the declared guard was Go with it's; the answers' is `press`, which lets a pair through | minor | applied |
| F106 | 6 | R19 | form reading | the uncapped split | `ledger.answers_of` takes the mark off by ledgerboard's regex, not `mail.answer_mark`, and TD-9002's reader bullet still named the capped split | minor | applied |
| F107 | 6 | R19 | synopsis | a steer's lapse | the synopsis left out the old steer's lapse | minor | applied |
| F108 | 6 | R19 | synopsis | the look's hand-off | the synopsis left out a filled Not right's hand-off through Answer… | minor | applied |
| F109 | 6 | R19 | record | the header | F102–F104, minor, are unread too | minor | applied |
| F110 | 6 | R20 | build wording | the `press` guard | `press` opens the answers' fold, not their drawing; the draw guard named | minor | applied |
| F111 | 6 | R20 | record | the header | the closing fact-check's own minor fixes were not named as read by its re-run | minor | applied |

**Rounds**

- R1 · 1 · fact-check · design-prep: PASS · TD-1557 · 749583a43faa · base af3d43692a4f · claims 18 · rules 4 · new 0 · waived 13
- R2 · 1 · design · design-prep: PASS · TD-1557 · 5b99eb7a8c73 · base af3d43692a4f · claims 25 · rules 4 · new 0 · waived 13
- R3 · 1 · design · design-prep: PASS · TD-1557 · 1f9ac3b138ff · base af3d43692a4f · claims 33 · rules 5 · new 0 · waived 12
- R4 · 2 · fact-check · design-prep: PASS · TD-1557 · 254db0edf58f · base af3d43692a4f · claims 36 · rules 6 · new 0 · waived 12
- R5 · 2 · design · design-prep: PASS · TD-1557 · 31f6dd08b715 · base af3d43692a4f · claims 42 · rules 6 · new 0 · waived 12
- R6 · 2 · design · design-prep: PASS · TD-1557 · c3399b630671 · base af3d43692a4f · claims 45 · rules 6 · new 0 · waived 12
- R7 · 3 · fact-check · design-prep: PASS · TD-1557 · b32019011304 · base af3d43692a4f · claims 47 · rules 6 · new 0 · waived 13
- R8 · 3 · design · design-prep: PASS · TD-1557 · b4af748cb54f · base af3d43692a4f · claims 47 · rules 6 · new 0 · waived 13
- R9 · 3 · design · design-prep: PASS · TD-1557 · 9a486bf383c0 · base af3d43692a4f · claims 48 · rules 6 · new 0 · waived 13
- R10 · 4 · fact-check · design-prep: PASS · TD-1557 · f21a4192f0c1 · base af3d43692a4f · claims 49 · rules 6 · new 0 · waived 13
- R11 · 4 · design · design-prep: PASS · TD-1557 · 07f3596f1372 · base af3d43692a4f · claims 50 · rules 6 · new 0 · waived 13
- R12 · 4 · design · design-prep: PASS · TD-1557 · f0d99669c17c · base af3d43692a4f · claims 53 · rules 6 · new 0 · waived 14
- R13 · 5 · fact-check · design-prep: PASS · TD-1557 · 23d7147cd338 · base af3d43692a4f · claims 54 · rules 6 · new 0 · waived 14
- R14 · 5 · design · design-prep: PASS · TD-1557 · 9d6899c4a6cb · base af3d43692a4f · claims 56 · rules 6 · new 0 · waived 14
- R15 · 5 · design · design-prep: PASS · TD-1557 · 99fee5f9007b · base af3d43692a4f · claims 60 · rules 6 · new 0 · waived 14
- R16 · 6 · fact-check · design-prep: PASS · TD-1557 · 9e34ab3266a8 · base af3d43692a4f · claims 63 · rules 6 · new 0 · waived 14
- R17 · 6 · design · design-prep: PASS · TD-1557 · 5da5477e8fe9 · base af3d43692a4f · claims 64 · rules 6 · new 0 · waived 14
- R18 · 6 · design · design-prep: PASS · TD-1557 · ef58a1d8bd98 · base af3d43692a4f · claims 65 · rules 6 · new 0 · waived 14
- R19 · 6 · fact-check · design-prep: PASS · TD-1557 · 5026126424b7 · base af3d43692a4f · claims 66 · rules 7 · new 0 · waived 14
- R20 · 6 · fact-check · design-prep: PASS · TD-1557 · 62fade362456 · base af3d43692a4f · claims 66 · rules 7 · new 0 · waived 14
- R21 · 6 · fact-check · design-prep: PASS · TD-1557 · 7addf6e22a86 · base af3d43692a4f · claims 66 · rules 7 · new 0 · waived 14
- final · design-prep: PASS · TD-1557 · 2772b4b1088a · base af3d43692a4f · claims 66 · rules 7 · new 0 · waived 14 (the result commit after it adds only this line, to the record, which the script does not read)
