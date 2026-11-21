# Writing a flow

A flow says how a ledger entry moves from filed to done. It is one YAML file. You write it, then run
`flowcheck.py <file>`; the flow is usable only when the check prints `OK`.

## The idea

- A flow is a list of **stages**. An entry is in one stage at a time.
- A stage is one session's sitting: it has a **model**, and an ordered list of **actions** the session does.
- Each action finishes with one of its own fixed **outcomes**. The session reports the outcome; a command
  checks the facts before accepting it.
- For each outcome of each action, the flow says where the entry goes **next**.
- Every time an entry enters a stage, a **fresh session** takes it. It reads the entry and its pull request
  and does what is still needed. No session keeps an entry across stages.

## The file

```yaml
format: 2
name: my-flow
stages:
  - name: Build                # free text, unique in the flow
    model: sonnet              # haiku, sonnet, opus or fable (cheapest to strongest)
    takes: other               # optional: which NEW entries start here (see "Ways in")
    actions:                   # in the order the session does them
      - build:                 # the action, then its outcomes: where each one goes
          pull-request-open: review
    stuck: {to: troubleshoot, limit: 1}   # optional: where a stuck session's entry goes
```

A stage's **key** is its name in lower case with spaces as hyphens: `Second read` is `second-read`.
Destinations use the key. An action with no outcomes listed is written `- merge: {}`.

## Actions and their outcomes

| Action | What the session does | Outcomes |
|---|---|---|
| `design` | writes a design | `pull-request-open`, `branch-pushed`, `not-needed` |
| `build` | writes the code, or continues work an earlier action or stage pushed | `pull-request-open`, `branch-pushed`, `design-needs-changing`, `not-needed` |
| `review` | reads the entry's open pull request and posts a verdict | `ship`, `changes-wanted` |
| `review-protected` | the same, but only for a pull request that touches the repo's protected paths | `ship`, `changes-wanted` |
| `fact-check` | checks a pull request's claims against the repo and posts a verdict | `ship`, `changes-wanted` |
| `merge` | merges the entry's pull request | `merged`, `cannot-merge` |

What the less obvious outcomes mean:

- `pull-request-open`: the work is in a pull request whose checks are green.
- `branch-pushed`: the work is pushed, with no pull request yet. It must go to `next-action` where the
  next action is `build`, or to a stage that has `build`; that `build` continues the same branch.
- `not-needed` on `design`: this entry needs no design. On `build`: the entry needs no work at all.
- `changes-wanted`: send it to a stage that has `build` (or `design`, for a design). Its fresh session
  fixes the same pull request.
- `cannot-merge`: the pull request changed since its review, or is red or conflicting. Send it to a stage
  that can fix it.
- `merged`: goes to `done` unless you say otherwise.
- `review-protected` on a pull request that touches no protected path is **skipped and counts as `ship`**.
  A stage with nothing else to do is then passed without starting a session. Which paths are protected is
  the repo's setting, not the flow's.

Every stage can also end as `stuck` (the session cannot go on). Its destination is the stage's `stuck:` key.

## Destinations

| Value | Meaning |
|---|---|
| a stage's key | the entry moves to that stage |
| `next-action` | the same session goes on to the next action in this stage |
| `person` | the entry waits for the person, with a question on their board |
| `done` | the entry is finished |

**An outcome you do not list goes to the person** (except `merged`, which goes to `done`). Leaving an
outcome out is allowed, and is the usual way to hand a rare case to the person.

### A limit

`{to: build, limit: 3}` means: this entry may take this move 3 times; a 4th time it goes to the person
instead. The count is per entry and per move. A limit may sit on any move to a stage.

### The person

- A pull request the person merges by hand finishes its entry: **a merged pull request always ends the
  entry, whatever stage it is in.** So "the person merges" is written by sending the outcome to `person`
  (for example `ship: person`), with no `merge` action anywhere.
- When the person answers a question, the entry goes back to the stage that asked, and a fresh session
  there reads the answer. To offer answers that go elsewhere, write
  `{to: person, answers: {"Try again": build, "Drop it": done}}`. An answer the person types in their own
  words always goes back to the stage that asked.

## Ways in

A new entry has no stage. `takes` says which stage it starts in:

- `takes: design-first`: entries that need a design before any code
- `takes: other`: every other entry
- `takes: any`: both kinds

Each kind must have exactly one stage that takes it. A stage with no `takes` only receives entries that
another stage sends it.

## How to write common wishes

- **Two reviewers must both pass it:** two stages, one after the other, each with `review` on its own
  model. The first's `ship` goes to the second.
- **One session designs and then builds:** one stage with `design` then `build`; send design's
  `branch-pushed` and `not-needed` to `next-action`.
- **A second try on a stronger model:** a second stage with the same action and another model; send the
  first stage's `stuck` to it with `limit: 1`.

## Rules the check enforces

1. Every destination is a stage that exists, or `next-action`, `person` or `done`. `next-action` needs a
   following action in the same stage.
2. Every outcome is written under the action it belongs to.
3. Every loop has a limit: if an entry can travel from a stage back to the same stage without passing the
   person, at least one move on that route carries a `limit`.
4. Every pull request that can be opened can reach a `merge` action, or an outcome that goes to the person.
5. `review`, `review-protected` and `fact-check` are never in the same stage as `design` or `build`: a
   reader is always a different session from the writer.
6. In a stage that has both, `merge` comes after `design` or `build`.
7. Each kind of new entry has exactly one way in.
8. Stage names are unique; every stage has a model from the list and at least one action.
9. Every stage can be reached: by `takes`, or as some outcome's destination.

When a flow is OK the check also prints what goes to the person, so you can see whether that is what you meant.

## A complete example

```yaml
format: 2
name: build-review
stages:
  - name: Build
    model: opus
    takes: any
    actions:
      - build:
          pull-request-open: review
  - name: Review
    model: sonnet
    actions:
      - review:
          ship: next-action
          changes-wanted: {to: build, limit: 3}
      - merge:
          cannot-merge: {to: build, limit: 3}
```
