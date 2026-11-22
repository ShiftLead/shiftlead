# Writing a flow

A flow says how a ledger entry moves from filed to merged. It is one YAML file. You write it, then run
`flowcheck.py <file>`; the flow is usable only when the check prints `OK`.

## The idea

- A flow is a list of **stages**. An entry is in one stage at a time.
- A stage does **one kind of work**: `design`, `build` or `review`. It has a **model**.
- Every time an entry enters a stage, a **fresh session** on that model takes it. It reads the entry, its
  pull request and any review of it, and does what is still needed. No session keeps an entry across stages.
- The session finishes by reporting one of the stage's fixed **outcomes**. A command checks the facts before
  accepting it.
- For each outcome, the flow says where the entry goes **next**.
- All of an entry's work is on **one pull request**. The first stage that pushes work opens it; a later
  build stage pushes onto the same one.

## The file

```yaml
format: 3
name: my-flow
max-moves: 25                  # optional: see "A limit"
stages:
  - name: Build                # free text, unique in the flow
    does: build                # design, build or review
    model: sonnet              # haiku, sonnet, opus or fable (cheapest to strongest)
    takes: other               # optional: which NEW entries start here (see "Ways in")
    brief: security-review     # optional: a brief of the person's own, in place of the standard one
    also: Look hardest at src/auth.   # optional: text added after the brief, for this stage only
    work-pushed: review        # an outcome of this stage, and where it goes
    other: {to: troubleshoot, limit: 1}
audits:                        # optional: see "Audits"
  - name: Docs audit
    model: sonnet
    every: 10 merged-pull-requests
    brief: docs                # docs, tests or code, or the name of a brief of the person's own
support:                       # optional: the model each built-in seat runs on
  tech-lead: opus
```

A stage's **key** is its name in lower case with spaces as hyphens: `Second read` is `second-read`.
Destinations use the key. Outcomes are written as keys of the stage itself.

## Kinds of stage and their outcomes

| `does` | What the session does | Outcomes |
|---|---|---|
| `design` | writes a design for the entry | `work-pushed`, `no-design-needed` |
| `build` | writes code, tests or documents for the entry, or continues what an earlier stage pushed | `work-pushed`, `design-needs-changing`, `not-needed` |
| `review` | reads whatever is on the entry's pull request and gives a verdict | `ship`, `changes-wanted` |

Every stage also has the outcome `other`: nothing above fits, for example the session is stuck on something
it cannot get past. It must give a reason.

What the outcomes mean:

- `work-pushed`: the stage's work is pushed and the pull request is open. Its checks must be green, unless
  the entry goes on to another build stage, which is expected to finish the work.
- `no-design-needed`: this entry needs no design and can be built as it is; send it to the build stage.
- `not-needed` (a build stage): the entry needs no work at all; leave it out, so the person decides whether
  to archive the entry.
- `design-needs-changing`: the builder found the design cannot be built as written. In a flow with no
  design stage, leave it out, so it goes to the person.
- `ship`: the reviewer passes the pull request as it now stands.
- `changes-wanted`: send it to a build stage (or a design stage, for a design). Its fresh session reads the
  review and fixes the same pull request.

A design's builds are separate entries: the design files them, and each starts as a new entry of its own.
A design is finished when its own pull request is merged.

There is no merge stage, no test stage and no stage that does two kinds of work. Running and fixing the
tests is part of `build`. A narrower read (a security review, a fact-check) is a `review` stage.

## Destinations

| Value | Meaning |
|---|---|
| a stage's key | the entry moves to that stage |
| `merge` | the pull request is merged and the entry is finished; allowed only on `work-pushed` and `ship` |
| `person` | the entry waits for the person, with a question on their board |

**An outcome you do not list goes to the person.** Leaving an outcome out is allowed, and is the usual way
to hand a rare case to the person.

### Merge

`ship: merge` merges the pull request with no session of its own, so no model is spent on it. A merge is
refused when the pull request changed after its verdict, is red, conflicts, or fails the repo's own ledger
and board checks. Say where a refused merge goes with `{to: merge, refused: {to: build, limit: 3}}`; with
plain `merge`, a refused merge goes to the person. A refusal only the person can cure, such as a go-ahead
the repo requires, always goes to the person and uses up no limit.

### A limit

`{to: build, limit: 3}` means: this entry may take this move 3 times; a 4th time it goes to the person
instead. So "show me after three rounds of changes" is `limit: 2`, because the third is the one the person
sees. The count is per entry and per move. A limit may sit on any move to a stage, including `refused`.

`max-moves`, at the top of the file, caps the whole trip: after that many moves from one stage to another
(a move to the person or to `merge` does not count), the next one goes to the person instead. It is 25
when you leave it out.

A question raised by a limit or by the cap always offers *Carry on*. That answer, or one the person types
in their own words, lets the blocked move happen and starts the counts again.

### The person

- A pull request the person merges by hand finishes its entry: **a merged pull request always ends the
  entry, whatever stage it is in.** So "the person merges" is written by sending the outcome to `person`
  (for example `ship: person`), with no `merge` anywhere.
- When the person answers a question, the entry goes back to the stage that asked, and a fresh session
  there reads the answer. To offer answers that go elsewhere, write
  `{to: person, answers: {"Try again": build, "A second opinion": second-read}}`; an answer goes to a stage.
  An answer the person types in their own words goes back to the stage that asked.

## Ways in

A new entry has no stage. `takes` says which stage it starts in:

- `takes: design-first`: entries that need a design before any code
- `takes: other`: entries that are ready to build
- `takes: any`: both kinds

Each kind must have exactly one stage that takes it, even in a flow with no design stage: there, the
first build stage is written `takes: any`, and an entry that asked for a design is simply built. A stage
with no `takes` only receives entries that another stage sends it. A review stage never takes new entries.

## A review that runs only sometimes

`only-when: protected-files` on a review stage means it reads only pull requests that touch the files the
repo marks as protected. For any other pull request the stage is **passed without starting a session, and
counts as `ship`**. Which files are protected is the repo's setting, not the flow's.

## Audits

An audit is not a stage and no entry passes through it. It starts on a clock, looks where its brief says,
and files each problem it finds as a new entry, which then enters the flow by its own way in. It fixes
nothing. Each audit has:

- `name`, `model`
- `every`: `<n> merged-pull-requests`, `<n> hours` or `<n> days` (always the plural: `1 days`)
- `brief`: `docs`, `tests` or `code` (the standard audit briefs), or the name of a brief of the person's own
- `also`: optional text added after the brief, such as which folders to look in

Nothing can be sent to an audit.

## How to write common wishes

- **Two reviewers must both pass it:** two review stages, one after the other, each on its own model. The
  first's `ship` goes to the second.
- **A second try on a stronger model:** a second stage of the same kind on another model; send the first
  stage's `other` to it with `limit: 1`.
- **Tests first:** two build stages. The first writes the failing tests and its `work-pushed` goes to the
  second, which makes them pass on the same pull request.
- **Do not spend a strong model where it is not needed:** `only-when: protected-files` passes the stage with
  no session, and `merge` never uses a session.

## Rules the check enforces

1. Every destination is a stage that exists, or `merge` or `person`. Only `work-pushed` and `ship`
   can go to `merge`. Nothing goes to an audit.
2. Every outcome a stage lists belongs to its kind of work.
3. Every loop has a limit: if an entry can travel from a stage back to the same stage without passing the
   person, at least one move on that route carries a `limit`. A refused merge that goes back to a stage is
   part of such a route.
4. Every pull request that can be opened can reach a `merge`, or a `work-pushed` or `ship` that goes to the
   person.
5. No outcome goes to `done`: an entry is finished by a merge, or by the person.
6. Each kind of new entry has exactly one way in, and it is not a review stage.
7. Stage and audit names are unique; every stage has a `does` and a model from the lists.
8. Every stage can be reached: by `takes`, or as some outcome's destination.
9. `max-moves`, when given, is a whole number of 2 or more.
10. Every audit has a name, a model, an `every` and a `brief`.

## Briefs and the built-in seats

Each kind of stage has a standard brief, which is what the session is told. A stage may name a brief of the
person's own with `brief:`, and may add text after whichever brief it uses with `also:`. A narrower read,
such as a security review, is a review stage with a brief of the person's own.

`support:` sets the model for the seats every flow has: `tech-lead` (answers members' questions),
`board-answers`, `unheld-pull-requests`, `manager` and `sweeper`. A seat left out runs on its default.

The check warns, without failing, when a review stage uses the same model as a stage whose work it reads.

When a flow is OK the check also prints what goes to the person, so you can see whether that is what you meant.

## A complete example

```yaml
format: 3
name: build-review
stages:
  - name: Build
    does: build
    model: opus
    takes: any
    work-pushed: review
  - name: Review
    does: review
    model: sonnet
    ship: {to: merge, refused: {to: build, limit: 3}}
    changes-wanted: {to: build, limit: 3}
```
