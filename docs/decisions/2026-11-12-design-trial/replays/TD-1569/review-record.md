# Review record: TD-1569

**Design:** docs/design/4.9a-winding-down.md §4.9a *A Start beside a busy seat*, *A refused Start says why*; docs/design/4.9-org-team-project.md *Starting and stopping*, *Start reads the same pairing*; docs/design/4.5a-controls.md rows *team card: Start / Wind down / Stop now*, *team groups*; docs/design/4.7-cli.md *Teams*; docs/design/4.9b-techlead.md
**Class:** in-repo
**Decided:** pending
**Source:** rounds

| review | round | role | model | tokens | date |
|---|---|---|---|---|---|
| R1 | 1 | fact-check | sonnet? | 105984 | 2026-11-14 |
| R2 | 1 | fact-check | sonnet? | 72013 | 2026-11-14 |
| R3 | 1 | fact-check | sonnet? | 41692 | 2026-11-14 |
| R4 | 1 | design | fable? | 133028 | 2026-11-14 |
| R5 | 1 | design | sonnet? | 85748 | 2026-11-14 |
| R6 | 2 | fact-check | sonnet? | 118374 | 2026-11-14 |
| R7 | 2 | fact-check | sonnet? | 48545 | 2026-11-14 |
| R8 | 2 | fact-check | sonnet? | 33676 | 2026-11-14 |
| R9 | 2 | design | fable? | 127515 | 2026-11-14 |
| R10 | 2 | design | sonnet? | 128879 | 2026-11-14 |
| R11 | 3 | fact-check | sonnet? | 113481 | 2026-11-14 |
| R12 | 3 | fact-check | sonnet? | 44774 | 2026-11-14 |
| R13 | 3 | design | fable? | 146974 | 2026-11-14 |
| R14 | 3 | design | sonnet? | 111129 | 2026-11-14 |
| R15 | 4 | fact-check | sonnet? | 71617 | 2026-11-14 |
| R16 | 4 | design | fable? | 124564 | 2026-11-14 |
| R17 | 4 | design | sonnet? | 123356 | 2026-11-14 |
| R18 | 4 | fact-check | sonnet? | 94518 | 2026-11-14 |
| R19 | 4 | fact-check | sonnet? | 44219 | 2026-11-14 |

| id | round | by | topic | finding | class | status |
|---|---|---|---|---|---|---|
| F1 | 1 | R1 | the left manager on call | its id must be the members' controllers (`lead_id`) | build-changing | applied |
| F2 | 1 | R1 | the confirm's seats | nothing said where the confirm reads them; `members_down.seats` | build-changing | applied |
| F3 | 1 | R1 | `left[].why` | whether the clause keeps the name | build-changing | applied |
| F4 | 1 | R1 | the Close cure, waiting | reader-waiting not excluded; where the clauses are built | build-changing | applied |
| F5 | 1 | R1 | the start's order | checks, reading, closes, set-aside unordered | minor | applied |
| F6 | 1 | R1 | `seat_names` | manager on call a seat only by its mark; glossary missed the sweeper | minor | applied |
| F7 | 1 | R1 | `{techlead}`, `{manager}` | already the holder's id; the suffixed-id case | minor | applied |
| F8 | 1 | R1 | side effects on a left seat | `keep_mail_for`, `_mark_team_start` | minor | applied |
| F9 | 1 | R1 | the Start help paragraph | broke `test_help` at the design commit; moved to TD-9001 | minor | applied |
| F10 | 1 | R1 | fallback words | an idle declared holder's wording | minor | applied |
| F11 | 1 | R2 | the start mark | the pass-over reaches every start | minor | reopens F8 |
| F12 | 1 | R2 | fallback words | sat-out, held extra, person's session holders | minor | reopens F10 |
| F13 | 1 | R3 | the start mark | written at every create until a member is live | minor | reopens F11 |
| F14 | 1 | R3 | fallback words | a seat or the manager with no clause | minor | reopens F12 |
| F15 | 1 | R4 | the refusal's cure | some holders safe, some not: unstated | build-changing | reopens F4 |
| F16 | 1 | R4 | the refusal's words | a holder not of the crew (unrecorded tmux, another team) | build-changing | reopens F12 |
| F17 | 1 | R4 | fallback words | held extra and sat out cannot hold a launch name | minor | reopens F14 |
| F18 | 1 | R4 | Apply vs Start | "a live team is offered Apply, never Start" left standing | minor | applied |
| F19 | 1 | R4 | card vs start | team-wide reading vs per-holder rule; `left` vs `members_down.seats` | minor | applied |
| F20 | 1 | R4 | a race | a seat closed between the name check and the read | minor | reopens F5 |
| F21 | 1 | R4 | rule 9 | a manager on call told its last acts is a left seat | minor | applied |
| F22 | 1 | R4 | the left manager's id | the seats' creates and the result's `manager` read it too | minor | reopens F1 |
| F23 | 1 | R4 | card words | the not-concluded line, the glossary, `ao team list`, two seats | minor | applied |
| F24 | 1 | R4 | the safe-to-close test | an idle undeclared holder passed it | minor | applied |
| F25 | 1 | R4 | entry points | a session's `ao team start` on a members-down team | minor | applied |
| F26 | 1 | R4 | `finished`'s clauses | matched to holders by prefix; `clauses` keyed by name | minor | reopens F3 |
| F27 | 1 | R5 | live orphan seats | a renamed, suffixed or switched-off seat offered Start, then refused | build-changing | reopens F18 |
| F28 | 1 | R5 | the refusal, mixed holders | whether a left seat is named; a session's refusal order | build-changing | reopens F15 |
| F29 | 1 | R5 | the cure's command | `ao team stop --close` wraps up the other holders and the seat | minor | reopens F15 |
| F30 | 1 | R5 | a suspended seat | counted members down, yet the Start refuses | minor | reopens F19 |
| F31 | 2 | R6 | a person's session | named as crew yet `crew` leaves it out | build-changing | reopens F16 |
| F32 | 2 | R6 | the strict `waiting` read | taken on every Start would newly fail | minor | reopens F5 |
| F33 | 2 | R6 | "read once" | the existing reads must be restructured; `keep_mail_for` | minor | applied |
| F34 | 2 | R6 | the suffixed seat | "creates that name as today" is not what happens | minor | applied |
| F35 | 2 | R6 | declarations | `manager_id` not declared | minor | applied |
| F36 | 2 | R6 | a waiver | its cited line 978 should be 980 | minor | applied |
| F37 | 2 | R7 | the `list` read | it is every Start's; only `waiting` is conditional | build-changing | reopens F32 |
| F38 | 2 | R7 | the suffixed seat | a dead leftover pane is a supersede, not free | minor | reopens F34 |
| F39 | 2 | R8 | the suffixed seat | free vs supersede wording | minor | reopens F38 |
| F40 | 2 | R8 | declarations | the supersede claim undeclared | minor | applied |
| F41 | 2 | R9 | what a seat is | a renamed or dropped seat is not in `seat_names`; standing seats | build-changing | reopens F27 |
| F42 | 2 | R9 | the pass-over in `_pairing` | Apply and the rename lines read it; a second seat beside the first | build-changing | reopens F27 |
| F43 | 2 | R9 | two Starts at once | "a second Start is refused" false once seats are left | build-changing | applied |
| F44 | 2 | R9 | non-crew holders | whether today's tail stays; the separator | build-changing | reopens F16 |
| F45 | 2 | R9 | the rollup ⋯ menu | no Start for a members-down team | build-changing | applied |
| F46 | 2 | R9 | a session's refusal | its words unstated | minor | reopens F28 |
| F47 | 2 | R9 | the *not concluded* help | still says "has no Start yet" | minor | applied |
| F48 | 2 | R10 | the sweeper | still a removal on the card; recognised how | build-changing | reopens F42 |
| F49 | 2 | R10 | the standing-seat test | global or its own; `seat_names`' readers | build-changing | reopens F41 |
| F50 | 2 | R10 | Apply on a members-down card | two Apply marks possible | minor | reopens F18 |
| F51 | 2 | R10 | page gating | `stopped`, the third state, the consistency guard | minor | applied |
| F52 | 2 | R10 | false sentences | §4.9, §4.9b, §6 rule 9 | minor | applied |
| F53 | 2 | R10 | two Starts at once | a new failure from nothing live | minor | reopens F43 |
| F54 | 2 | R10 | a person's session | no cure for it | minor | reopens F44 |
| F55 | 2 | R10 | a failed `waiting` read | refuses a seats-only Start | minor | applied |
| F56 | 2 | R10 | TD-9001's tests | gaps | minor | applied |
| F57 | 2 | R10 | `ao team list` text | unspecified | minor | applied |
| F58 | 2 | R10 | a standing manager | the bug stays for its team | minor | applied |
| F59 | 3 | R11 | the sweeper on the card | the card's plan lacks the switch: a removal there | build-changing | reopens F48 (withdrawn by F66's fix: the sweeper is no standing seat) |
| F60 | 3 | R11 | the standing sweeper | `sweep_seat`'s repo-off and own-sweeper cases | build-changing | reopens F48 (withdrawn by F66's fix) |
| F61 | 3 | R11 | declarations | `ao team list`'s text, `_name_holder` | minor | applied |
| F62 | 3 | R11 | `rows`' switch | how rows gets it | minor | applied |
| F63 | 3 | R12 | the card vs the Start | Apply would sit out the sweeper the Start leaves | build-changing | reopens F59 |
| F64 | 3 | R12 | declarations | a claim's line off by one | minor | applied |
| F65 | 3 | R13 | a seat's extra | `scale` alone matches a worker line's extra | build-changing | reopens F41 |
| F66 | 3 | R13 | the switch in the card's plan | contradicts §4.9b *The switch* three ways | build-changing | reopens F63 |
| F67 | 3 | R13 | the third header state | its words and order | minor | applied |
| F68 | 3 | R13 | the cure's joins | several holders; *wait* for a holder that will not finish | minor | reopens F15 |
| F69 | 3 | R13 | the confirm vs the press | a team concluded by the press closes the seat | minor | applied |
| F70 | 3 | R13 | the terminal's rule | per holder, wider than the card's | minor | applied |
| F71 | 3 | R13 | the work note | not drawn on a live card | minor | applied |
| F72 | 3 | R14 | §4.5a's example | still names the sweeper as left | build-changing | reopens F66 |
| F73 | 3 | R14 | a seat closed mid-start | its mail not kept | minor | reopens F20 |
| F74 | 3 | R14 | §4.7's members down | omits *not concluded* | minor | applied |
| F75 | 3 | R14 | the *not concluded* line | drawn or not on a members-down card | minor | applied |
| F76 | 3 | R14 | the glossary | looser than the rule | minor | applied |
| F77 | 4 | R15 | the person's own session | TD-9002 dropped the cure the design keeps | build-changing | reopens F68 |
| F78 | 4 | R15 | a working Settings sweeper | its team stays without a Start; unstated | minor | applied (stated as a known gap) |
| F79 | 4 | R15 | a seat found dead mid-start | an exited one's mail is not kept | minor | reopens F73 |
| F80 | 4 | R15 | the *not concluded* line | "same clauses" only roughly true | minor | reopens F75 |
| F81 | 4 | R15 | declarations | a claim's line | minor | applied |
| F82 | 4 | R16 | the history | still names the sweeper as left | build-changing | reopens F72 |
| F83 | 4 | R16 | the dead-holder rebuild | its scope and how the verdict is built | minor | reopens F79 |
| F84 | 4 | R16 | a manager on call | its record on call, its definition now standing | minor | reopens F41 |
| F85 | 4 | R16 | the person's own session | which sessions; the safe-to-close sentence | minor | reopens F77 |
| F86 | 4 | R16 | words | the left line, the header join, the toast, the cure's join | minor | reopens F67 |
| F87 | 4 | R16 | the *work waiting* row | not amended | minor | reopens F71 |
| F88 | 4 | R16 | the start mark | rule 8's single-member replay | minor | reopens F13 |
| F89 | 4 | R16 | "live seat" | where "standing seat" is meant | minor | applied |
| F90 | 4 | R16 | TD-9001's Location | omits app.py and app.js | minor | applied |
| F91 | 4 | R17 | the dead-holder rebuild | would rebuild a suspended verdict and lift a suspension | build-changing | reopens F83 |
| F92 | 4 | R17 | the controls' order | the card and the rollup ⋯ differ, unstated | minor | reopens F45 |
| F93 | 4 | R17 | *concluded wins* | a case the definition already rules out | minor | applied |
| F94 | 4 | R17 | the toast | may name fewer seats than the confirm | minor | reopens F86 |
| F95 | 4 | R18 | the synopsis heading | drops the entry title's last clause | minor | rejected: the full title is over the 120 columns `tests/test_synopses.py` allows, and the test does not compare the title |
| F96 | 4 | R18 | the synopsis | leaves out four choices; *restart wanted* | minor | applied |
| F97 | 4 | R18 | the *work waiting* row | "`ao team list` unchanged" reads against §4.7 | minor | applied |
| F98 | 4 | R18 | Log dates | the helper's Log lines dated 2026-11-15 | minor | rejected: `ledger.py` stamps the UTC day, the record the local one |

Statuses: every `reopens F<n>` row was applied in the same round.

How the rounds ended: at the cap (in-repo, 4), round 4's reviews raising build-changing findings (F82, F91). Trend, build-changing per round from the design reviews: 4, 7, 3, 2; from the fact-checks: 4, 2, 3, 1. Recurring topics: **which live seats a Start leaves** (F27 → F41, F42, F48, F49 → F59, F60, F63, F65, F66, F72 → F82), and **the refusal's words for its holders** (F15, F16, F28 → F31, F44 → F77). R8's two minor fixes (F39, F40) and R3's (F13, F14) were read by the next design review, not by a fact-check re-run. Fixes no review has read: F91, F92, F93, F94 (R17's, all TD-9001's).

Decided:
- would have sent the end-of-rounds item: a `decide` line on docs/user_attention.md, `Context: TD-1569 decision (paul). Parts: TD-9001, TD-9002.`, answers `One more round (default) | Go | Hold: <note>`, recommending One more round because F91 (TD-9001: a `suspended` verdict is never rebuilt and refuses) is a build-changing fix no review has read, naming the two recurring topics with *is this the wrong design?* — the position taken on each: a standing seat (one the definition names now, or its extra) is left and nothing else; the refusal names each holder by its clause and offers Close only where safe; detail by build: TD-9001 F91, F92, F93, F94; TD-9002 none. Not sent (replay); TD-1569, TD-9001 and TD-9002 carry `**Blocked by:** decision (paul)` and an `**Ask:**`.
- would have posted the closing fact-check's evidence: R18 `cadence-review: BLOCK · sonnet · docs · 4 findings`, R19 `cadence-review: FIXED · sonnet · docs · 0 findings`; and would have asked `fact-check-ao-1` for the fact-check trial (outside the gate, no row).
- would have sent no steer: the label (*Start*, not *Start members*) and a session's start refused where a seat would be left follow from what was written, taken in by the designer.

Decided: replay ended — the cap (in-repo, 4 rounds; round 4's reviews raised build-changing F82 and F91, and the closing fact-check's re-run R19 raised nothing)

**Rounds**

- R1 · 1 · fact-check · design-prep: PASS · TD-1569 · 69c689bbf787 · base 90f56dd2090b · claims 16 · rules 3 · new 0 · waived 5
- R2 · 1 · fact-check · design-prep: PASS · TD-1569 · 56accbce851c · base 90f56dd2090b · claims 22 · rules 3 · new 0 · waived 5
- R3 · 1 · fact-check · design-prep: PASS · TD-1569 · 9d924b13691e · base 90f56dd2090b · claims 22 · rules 3 · new 0 · waived 5
- R4 · 1 · design · design-prep: PASS · TD-1569 · e3f646dc32ab · base 90f56dd2090b · claims 24 · rules 3 · new 0 · waived 5
- R5 · 1 · design · design-prep: PASS · TD-1569 · 0a7f604cc083 · base 90f56dd2090b · claims 27 · rules 3 · new 0 · waived 7
- R6 · 2 · fact-check · design-prep: PASS · TD-1569 · c0c3f3f7eeba · base 90f56dd2090b · claims 29 · rules 3 · new 0 · waived 7
- R7 · 2 · fact-check · design-prep: PASS · TD-1569 · 9ea734d6c91e · base 90f56dd2090b · claims 32 · rules 3 · new 0 · waived 7
- R8 · 2 · fact-check · design-prep: PASS · TD-1569 · affd3a1f4858 · base 90f56dd2090b · claims 32 · rules 3 · new 0 · waived 7
- R9 · 2 · design · design-prep: PASS · TD-1569 · 1e769371c5c8 · base 90f56dd2090b · claims 33 · rules 3 · new 0 · waived 7
- R10 · 2 · design · design-prep: PASS · TD-1569 · 8c106d0a9b99 · base 90f56dd2090b · claims 38 · rules 3 · new 0 · waived 9
- R11 · 3 · fact-check · design-prep: PASS · TD-1569 · 44f4337683eb · base 90f56dd2090b · claims 41 · rules 3 · new 0 · waived 9
- R12 · 3 · fact-check · design-prep: PASS · TD-1569 · 4c768b0d9614 · base 90f56dd2090b · claims 44 · rules 3 · new 0 · waived 9
- R13 · 3 · design · design-prep: PASS · TD-1569 · 43e4a3f69ddf · base 90f56dd2090b · claims 45 · rules 3 · new 0 · waived 9
- R14 · 3 · design · design-prep: PASS · TD-1569 · 97dc6e0aecc9 · base 90f56dd2090b · claims 45 · rules 3 · new 0 · waived 10
- R15 · 4 · fact-check · design-prep: PASS · TD-1569 · d2d3f07ffabe · base 90f56dd2090b · claims 45 · rules 4 · new 0 · waived 10
- R16 · 4 · design · design-prep: PASS · TD-1569 · 6d02a3e54f0b · base 90f56dd2090b · claims 45 · rules 5 · new 0 · waived 10
- R17 · 4 · design · design-prep: PASS · TD-1569 · cb72f7448a0d · base 90f56dd2090b · claims 45 · rules 5 · new 0 · waived 10
- R18 · 4 · fact-check · design-prep: PASS · TD-1569 · da0ea52fb153 · base 90f56dd2090b · claims 46 · rules 5 · new 0 · waived 10
- R19 · 4 · fact-check · design-prep: PASS · TD-1569 · 7aa565ff32bc · base 90f56dd2090b · claims 46 · rules 5 · new 0 · waived 10
- final · design-prep: PASS · TD-1569 · 379adcd4ae51 · base 90f56dd2090b · claims 46 · rules 5 · new 0 · waived 10 (the result commit after it adds only these record lines, which no check reads)
