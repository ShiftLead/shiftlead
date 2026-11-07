# Design synopses

One file per design, `TD-<design>.md`, written for the person: what the design does, from a high level, so they
can judge it without its minutiae (design §4.9c *The designer writes the synopsis*, §4.5 screen 6 *A design links
its synopsis*). The design text, its review record and an end-of-rounds item's detail are written for a reviewer;
this page is not. A design's Queue card and every item about it link it.

**Who writes it, and when.** Every design PR writes it: the first round's PR makes it, and each later round's PR,
a bought round's or a `Hold` revision's among them, rewrites it whole, in the present tense, so it says what the
design says at that PR's head. It is written last, after the round's fixes, and the closing fact-check reads it
with the rest of the diff: it says nothing the design does not, and leaves out none of the design's choices the
person would weigh.

## The shape

- A heading `# TD-<n>: <the entry's title>`, the title with its backticks dropped.
- Then four sections, in this order, each a few sentences or short bullets:
  - `## What it does`
  - `## The key choices, and why`
  - `## What it rules out`
  - `## What you will see`
- At most 40 non-blank lines as committed, headings counted, each line wrapped at 120 columns, so it reads on one
  screen.

## The writing rule

A synopsis is a message to the person (design §4.10 *How a message to a person is written*), read cold:

- plain words;
- no finding id (F12), no function, file, path or line reference, no backticks;
- a ledger id (TD-1476) only where it names other work the person knows by it.

The level, in Paul's words for TD-1476: *each pool member is a separate record, so the design stays simple;
members show on the team as seats; later members carry a backup indicator; pools only on question seats, the
techlead's is a later design.*

`tests/test_synopses.py` holds every synopsis here to the shape and to the rule's checkable part: the heading's
`# TD-<n>: ` prefix (the title after it is not compared, so a retitled entry never turns it red), the four
sections in order, the length and width, and no `F<n>`, backtick, `.py`, or `:<digits>` after a word holding a
`/` or ending in a file extension. A file named for an id the ledger does not hold, open or archived, fails.
