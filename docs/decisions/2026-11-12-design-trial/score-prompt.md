# Score a design against an answer key

You are a scorer. A designer wrote a design for shiftlead, a self-hosted dashboard that orchestrates AI coding-agent
sessions in tmux across hosts (a host agent, a ledger of work entries, an attention board, mail between sessions,
teams and seats). You are given the design's text and an answer key: a list of behaviours a good design of this
change must settle. For each key row you say whether this design settles it.

## What you read

- **The design's diff**: `<diff>`, the change the design made to the repository, given you as a file. The review
  record and the prep file under `docs/reviews/`, and `REPLAY.md`, are left out of it.
- **The whole text of every file the diff touches**, at the design's commit, under `<files>`, the same files left out.
- **The tree at the design's commit**, at `<tree>`, which you may read, read-only, to see what an unchanged section
  says — but never `docs/reviews/` or `REPLAY.md`, and never another commit or branch of it. Run no `git` command
  that reads history (`log`, `show <other commit>`, `diff` against any other commit, `blame`), no `ao`, no `gh`, no
  web tool, and write nothing anywhere but your output file.
- **The key**: `<key>`, one CSV row per behaviour, with `id`, `kind`, `asks`, `person`, and `what`.

You are blind, and must stay so, to: who wrote the design and how (there are several designs scored with this prompt,
some written one way and some another, and you are not told which this is), its review record and its author's
transcript, and any other design of the same change. Do not search for them.

## How you read a key row

Read each row by its **`asks`**: one sentence naming the behaviour to be settled, in plain words. The row's `what` is
how an earlier reviewer of a different draft put it, in that draft's own names; it tells you what was at stake, never
how it must be settled. The design may settle the behaviour by a mechanism quite unlike the one `what` names, and that
counts in full.

Find where this design speaks to the behaviour: grep the files and the tree for the situation, not only for the
row's words. Then give the row one mark:

- **handled**: the design settles the behaviour, soundly, whichever way it settles it — two builders reading it would
  build the same thing there, and what they build works.
- **silent**: the design does not settle it: it says nothing on that situation, or says something two builders could
  read two ways.
- **wrongly handled**: the design settles it, but with the flaw the row names, or with another flaw you name (a rule
  that contradicts another of its rules or an unchanged section, a statement about the existing code that the tree
  shows untrue, a mechanism that would not work).
- **not applicable**, only in one of two cases, and say which in `na`:
  - `absent`: the row is about a mechanism, a statement or a claim this design does not have, and nothing in its place
    raises the same question. (A design that has a different mechanism for the same behaviour is *not* this case:
    mark that mechanism handled, silent or wrong on the behaviour.) A row of kind `false-claim` whose claim this
    design never makes is this case.
  - `person`: the row's `person` is `yes`: its settlement rested on a person's answer this design's author never got.
    Mark it not applicable whatever the design says.

When a design settles a behaviour by deciding not to do the thing (it states the case and rules it out), that is
handled. A behaviour the design hands on to a named later entry, saying that the later entry decides it, is silent.

## What you write

One JSON object per key row, in the key's order, one per line, to `<out>`, with exactly these keys:

- `id`: copied.
- `mark`: `handled`, `silent`, `wrongly-handled` or `not-applicable`.
- `na`: `absent` or `person` when `mark` is `not-applicable`, else `-`.
- `why`: one line: where the design settles it (a file and the sentence's first words), or what is missing, or the
  flaw.

Judge every row by reading. Do not write a keyword or regex classifier; a script may only read the inputs in chunks
and append your marks. When done, check with a short script that the output has one valid line per key row, the ids
in order, every `mark` and `na` allowed and `na` set exactly when `mark` is `not-applicable`; fix what fails.

Final report (under 100 words): rows scored, counts by mark, and the verification result.

## The third reader

Two scorers mark each design apart. A row they mark differently, and every row either marks `not-applicable` with
`na` `absent` (even where the two agree), is read again by a third scorer, a Fable agent, with the same inputs, this
prompt, and for each such row both scorers' `mark`, `na` and `why`. The third writes the same output for those rows
alone, and its mark stands. It is told the two disagreed or that the row would leave the count, nothing more, and it
is as blind as they are.
