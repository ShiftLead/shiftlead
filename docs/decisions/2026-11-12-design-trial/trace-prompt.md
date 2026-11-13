# Trace an escape to its design, or not

You are a labeller. shiftlead, a self-hosted dashboard that orchestrates AI coding-agent sessions in tmux across
hosts, designs a change before it is built: a design PR writes the design's sections under `docs/design/` and files
build entries under `docs/ledger/`, and a builder then builds each entry in its own PR. Something that went wrong
after a design's review rounds ended — a finding raised on a build's PR, or a later PR that fixed the build — is an
**escape**. You say, for each escape, whether it traces to the design.

## What you read, for each escape

- **The escape**: either one numbered finding from the review-evidence comment of the build's PR, or a **fix PR**
  (its title, body and diff), merged after the build and naming it.
- **The build's entry**, `docs/ledger/TD-<n>.md`, as it stood when the build's PR was opened.
- **The design's sections at its merge commit**: the files under `docs/design/` its design PRs touched, whole, at the
  commit that merged its last design PR, and the design's own entry there. You may grep the rest of `docs/design/` at
  that commit for a term.

You are not told which designs were written which way, nor how many escapes any design has; there are designs of more
than one kind among those you label. Do not search the repository's history, pull requests or other commits for it,
and run no `ao`, `gh` or web tool. Write nothing but your output file.

## The label

- **traces** (`yes`): the design was **silent or wrong** on what went wrong. Either it did not settle the behaviour,
  so the builder had to choose and chose badly, or two builders could have read it two ways; or it settled the
  behaviour wrongly — a rule that does not work, contradicts another rule or an unchanged section, or rests on a
  statement about the existing code that was untrue. A fix that changed the design's own text to repair the behaviour
  is a strong sign of this, but read the design to confirm it.
- **does not trace** (`no`): the design settled the behaviour rightly and the build did not follow it; or the escape
  is about something below the design's level — an implementation bug, a typo, a test's flakiness, a lint or format
  rule, a missing test of a behaviour the design states plainly, wording of a help text the design does not give; or
  it is outside what the design covers.

The label is one of the two: the trial counts the escapes that trace. Where the escape and the design leave you
unsure, give the label the reading favours and set `conf` to `low`; the report shows the low-confidence labels apart.

Read the escape first and name, to yourself, the behaviour that went wrong in plain words. Then find where the design
speaks to that behaviour, by the situation and not only by the escape's words, and decide.

## What you write

One JSON object per escape, in the input's order, one per line, to `<out>`, with exactly these keys:

- `id`: copied from the input.
- `traces`: `yes` or `no`.
- `conf`: `high`, or `low` where the escape and the design leave you unsure.
- `why`: one line: the design's sentence that was silent, wrong or right on it (its file and first words), or why the
  escape is below or outside the design.

Judge every escape by reading it; do not write a keyword or regex classifier. When done, check with a short script
that the output has one valid line per input row, the ids in order and every `traces` and `conf` allowed; fix what fails.

Final report (under 100 words): escapes labelled, counts by label and by `conf`, and the verification result.
