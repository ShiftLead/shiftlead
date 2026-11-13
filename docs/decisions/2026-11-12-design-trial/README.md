# The trial's answer keys and prompts (TD-1773)

The answer keys the three replays are scored against, and the two prompts of the trial's readings, written before
any replay runs so that nothing is fitted to a result (design §4.9c *The trial of the new shape*, *The answer key*,
*The score*; TD-1722). The originals' captured turns are in [`originals/`](originals/README.md).

## The keys

A key row is a finding of the original's review record of origin `original`, kind `unspecified`, `wrong-mechanism`,
`contradiction` or `false-claim`, with an outcome that does not start `rejected`; TD-1470's from its rounds 1 to 8.

| key | rows | unspecified | wrong-mechanism | false-claim | contradiction | in a hard situation |
|---|---|---|---|---|---|---|
| [`keys/TD-1557.csv`](keys/TD-1557.csv) | 57 | 26 | 16 | 12 | 3 | 21 |
| [`keys/TD-1569.csv`](keys/TD-1569.csv) | 44 | 31 | 9 | 4 | 0 | 16 |
| [`keys/TD-1470.csv`](keys/TD-1470.csv) | 81 (68 in rounds 1–4) | 53 | 13 | 14 | 1 | 28 |

By situation (`-` where the pattern pass names none, as it does for every false claim; the hard situations are
interaction, concurrency, when, ends, who, failure and restart):

| situation | TD-1557 | TD-1569 | TD-1470 |
|---|---|---|---|
| interaction | 12 | 6 | 1 |
| scope | 6 | 9 | 11 |
| shape | 11 | 7 | 7 |
| display | 3 | 6 | 9 |
| which | 4 | 2 | 9 |
| when | 0 | 2 | 9 |
| who | 4 | 3 | 6 |
| ends | 0 | 0 | 7 |
| failure | 3 | 3 | 1 |
| concurrency | 2 | 2 | 2 |
| empty-first | 0 | 0 | 3 |
| restart | 0 | 0 | 2 |
| - | 12 | 4 | 14 |

No row has `person` yes: no key row's outcome rests on a person's answer.

## How each file was made

- **`labels.csv`** — TD-1557's and TD-1569's records (91 and 89 findings), read at `d798a53d` (#3511's merge, where
  both records are complete), labelled with the analysis's
  [`classify-prompt.md`](../2026-11-11-design-review-findings/classify-prompt.md) by two Sonnet labellers apart, on
  2026-11-13. They agreed on kind for 55 of TD-1557's 91 and 69 of TD-1569's 89, and on origin for 76 of 91 and 87 of
  89. The 64 rows on which they differed on either were read by a third Sonnet labeller, blind to the two, whose kind
  and origin stand there; catch and area are the first labeller's. `python keys.py merge labellers` writes it from the
  labellers' outputs, kept in [`labellers/`](labellers/) (`a-`, `b-` and `c-` the classify passes, `p-` the pattern
  pass), and prints the agreement above.
- **`patterns.csv`** — the same 180 findings, with their merged labels, labelled by one Sonnet labeller with the
  analysis's [`pattern-prompt.md`](../2026-11-11-design-review-findings/pattern-prompt.md) on 2026-11-13; written by
  the same `merge`.
- **TD-1470's labels** are the analysis's own ([`labels.csv`](../2026-11-11-design-review-findings/labels.csv),
  [`patterns.csv`](../2026-11-11-design-review-findings/patterns.csv)), its record read at the analysis's commit
  `df866eeb8`.
- **`asks.csv`** — one row for each of the 182 key rows, written by one Sonnet reader on 2026-11-13 from the
  record's row and the original's design at its merge (TD-1557 at `d798a53d`, #3511; TD-1569 at `a6474184`, #3465;
  TD-1470 at `365683cb`, #3246, the last of its rounds 1 to 8): `asks`, one sentence naming in no mechanism's names
  the behaviour the finding wanted settled, and `person`. The reader read each design's synopsis and entry and wrote
  most rows from the row itself; it named fifteen rows whose behaviour it could not state without the original's
  terms, whose `asks` are therefore general: TD-1557's F6, F9, F24, F52, F60, F62, F63; TD-1569's F46, F50;
  TD-1470's F4, F151, F165, F174, F177, F187. `python keys.py asks <file>` writes it from the reader's output, checked
  against the keys' rows.
- **`keys/TD-<n>.csv`** — `python keys.py` rebuilds all three from the labels, `asks.csv` and the records (read by
  `git show` at the commits above, never the work tree), and prints the counts by situation. Its columns: id, round,
  topic, what, class (the reviewer's own), outcome, kind, situation, `q` (the pattern pass's question), asks, person.
- **[`score-prompt.md`](score-prompt.md)** — the scorers' prompt: their inputs (the result's diff and touched files
  without `docs/reviews/` and `REPLAY.md`, the tree read-only, the key), what they are blind to, each row read by its
  `asks`, the four marks and the two cases of not applicable, and the third reader's inputs.
- **[`trace-prompt.md`](trace-prompt.md)** — the escape labeller's prompt: traces to the design or not, its inputs
  (the escape, the build's entry, the design's sections at its merge), and its blindness to which half a design is in.
