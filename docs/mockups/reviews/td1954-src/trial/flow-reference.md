# Writing a flow

A flow says how a ledger entry moves from filed to done. It is one YAML file. You write it, then run
`flowcheck.py <file>`; the flow is usable only when the check prints `OK`.

## The idea

- A flow is a list of **stages**. An entry is in one stage at a time.
- A stage is one session's sitting: it has a **model**, and an ordered list of **actions** the session does.
- Each action can finish with one of a fixed set of **outcomes**. The session reports the outcome; a command
  checks the facts before accepting it.
- For each outcome the flow says where the entry goes **next**.
- Every time an entry enters a stage a **fresh session** takes it. A session never keeps an entry across stages.

## The file

```yaml
format: 2
name: my-flow
stages:
  - name: Build                # free text, unique in the flow
    model: sonnet              # one model; or a list, taken in turn, for a stage that reviews
    takes: other               # optional: which NEW entries start here (see "Ways in")
    actions: [build]           # in the order the session does them
    next:                      # outcome: destination
      pull-request-open: review
      stuck: {to: troubleshoot, limit: 1}
```

A stage's **key** is its name in lower case with spaces as hyphens: `Second read` is `second-read`.
Destinations use the key.

## Actions and their outcomes

| Action | What the session does | Outcomes |
|---|---|---|
| `design` | writes a design and opens its pull request | `pull-request-open`, `not-needed` |
| `build` | writes the code and opens its pull request, or pushes a branch for a later stage to finish | `pull-request-open`, `branch-pushed`, `design-needs-changing`, `not-needed` |
| `review` | reads the entry's open pull request and posts a verdict | `ship`, `changes-wanted` |
| `fact-check` | checks a pull request's claims against the repo and posts a verdict | `ship`, `changes-wanted` |
| `merge` | merges the entry's pull request | `merged`, `cannot-merge` |

Every stage also has the outcome `stuck`, whatever its actions.

Notes on single outcomes:

- `branch-pushed`: work is pushed with no pull request yet. The next stage must have `build`, and continues it.
- `changes-wanted`: send it to the stage that wrote the pull request, so it can fix it.
- `cannot-merge`: the pull request changed since its review, or is red or conflicting. Send it to the stage
  that wrote it.
- `merged`: goes to `done` unless you say otherwise.

`review` takes one setting. Write `{review: protected-paths}` in the actions list to review only pull
requests that touch the repo's protected paths; the action is skipped for the rest, and the session moves
to its next action. Plain `review` reads every pull request.

## Destinations

A `next` value is one of:

| Value | Meaning |
|---|---|
| a stage's key | the entry moves to that stage |
| `next-action` | the same session goes on to the next action in this stage |
| `person` | the entry waits for the person, with a question on their board |
| `done` | the entry is finished |

To limit a move, write `{to: <destination>, limit: <n>}`: the entry may take that move n times, and the
next time it goes to the person instead. A limit may sit on any move.

**An outcome you do not list goes to the person** (except `merged`, which goes to `done`). Leaving outcomes
out is allowed, and is how you hand a case to the person.

## Ways in

A new entry has no stage. `takes` says which stage it starts in:

- `takes: design-first`: entries that need a design before any code
- `takes: other`: every other entry
- `takes: any`: both kinds

Each kind must have exactly one stage that takes it. A stage with no `takes` only receives entries that
another stage sends it.

## Rules the check enforces

1. Every destination is a stage that exists, or `next-action`, `person` or `done`. `next-action` needs a
   following action in the same stage.
2. Every outcome named under `next` belongs to one of the stage's actions (or is `stuck`).
3. Every loop has a limit: if an entry can travel from a stage back to the same stage, at least one move on
   that route carries a `limit`.
4. Every pull request that can be opened can reach a `merge`, or goes to the person.
5. `review` and `fact-check` are never in the same stage as `design` or `build`: a reader is always a
   different session from the writer.
6. `merge` comes after the pull request exists: it is never in a stage's actions before `design` or `build`
   opens one, and a stage with `merge` alone is fine.
7. Each kind of new entry has exactly one way in.
8. Stage names are unique, and every stage has a model.

The check also prints, as information, every outcome that goes to the person and any stage nothing can reach.

## A complete example

```yaml
format: 2
name: build-review
stages:
  - name: Build
    model: opus
    takes: any
    actions: [build]
    next:
      pull-request-open: review
  - name: Review
    model: sonnet
    actions: [review, merge]
    next:
      ship: next-action
      changes-wanted: {to: build, limit: 3}
      cannot-merge: {to: build, limit: 3}
```
