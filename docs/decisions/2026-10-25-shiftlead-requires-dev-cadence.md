# ADR 2026-10-25: ShiftLead requires dev-cadence, and the person's own texts live in their dev-cadence layer

**Status:** decided 2026-10-25 by Paul (*Go with your recommendations*): option 4 — Q1 yes, Q2 yes, Q2a and Q2b as recommended (drafted with him, session `ao-shiftlead-prompts`, after two Sonnet and two Fable rounds reached READY)
**Date:** 2026-10-25
**Supersedes:** in [ADR 2026-10-12](2026-10-12-ledgerboard-dev-cadence-shiftlead.md), the layer
table's *never owns … a requirement that dev-cadence be installed* and its section *What ShiftLead requires of
a repo, and what it only uses*, as listed under *Decision* 2; the rest of that ADR (the three layers,
ledgerboard) stands.
**Related:** TD-1009 (this decision), TD-993 (Told at start moves to the Session card and the Transcript,
where it prompted this), TD-657 / TD-662 (the director's preference layers, designed, not built), TD-681
(the home merges a sync PR), TD-588 (the briefs' layout slots), TD-062 (the live copy); dev-cadence TD-126
(the personal layer), TD-128, TD-129 and its
[plan 2026-10-25](https://github.com/ShiftLead/dev-cadence/blob/main/docs/plans/2026-10-25-pinned-not-synced.md)
(dev-cadence pinned, not synced); [ADR 2026-10-08](2026-10-08-agentorc-dev-cadence-split.md); design §4.7,
§4.8, §4.9, §4.9b, §5, §6, §8

## Context

**What ADR 2026-10-12 decided.** Paul, 2026-10-12: dev-cadence should work in any repo and any session with
no ShiftLead on the machine, and *ShiftLead should recommend dev-cadence but not require it*. So ShiftLead
carries a path for a repo without dev-cadence:
- the built-in briefs' layout slots each have a sentence for an absent seam (§5 *The layout slots*:
  `{gate}` *no gate: a person merges*, `{board}`, `{ledger_check}`, `{cadence_rules}` *no cadence rules: the
  repo's README says how a change lands*);
- `ao repo init` writes a bare ledger for a repo with no seeds (§4.7);
- each reader of a dev-cadence file degrades silently when it is absent: the roster, the gate
  (`sessionorc/cadence.py`), convention notices, worktree setup, the SessionStart line (the ADR's own list).

No repo on this machine's roster exercises that path: samscrape, contractmatch, pneuma-ops, shiftlead,
guardians-devenv and ledgerboard are all synced, and dev-cadence is its own source. (Other machines and
other people are unchecked.) Paul, 2026-10-25: *we talked previously about letting someone use a different
cadence mechanism (other than dev-cadence) but I wonder if that is needless complication, especially given
that we are building personal prefs into dev-cadence now.*

**What a person can change today.** Prompted by TD-993 (the start context made visible: *as soon as users
can see it they will want the ability to modify it*):
- the role briefs take a repo's or a team's supplement (`roles.<name>.brief`, a definition's `brief:`),
  filled into the template's *This repo's rules* slot (§4.8); nothing of the person's own, across repos;
- `entry.md` (an Add entry session's start context) and `work.md` are read from the package alone
  (`repoconfig.entry_text`) and cannot be changed at all;
- the director's preferences are designed (TD-657) as `~/.shiftlead/preferences.md`, under the home's own
  git work tree (TD-210), which never pushes — so they do not follow the person to another machine.

**What dev-cadence now has.** TD-126's personal layer: the person's own rules in their own git repo,
private by default, cloned on each machine and named by a machine-wide `cadence.toml` key; read at session
start; rules keyed to the cadence § they change; `--effective` shows each rule's layer, line and commit; a
publish check over every tracked file before a layer goes public; others' layers read at a pinned ref and
never pulled. Slices 1–6 are built, and Paul's layer is live (dev-cadence #313): the private repo
`eyecantell/cadence-layer`, cloned at `~/cadence-layer`, its rules in `cadence-personal.md`, named by
`[[layers]] path` in `~/.config/dev-cadence/cadence.toml`. And its plan of the same date proposes that a
repo pins dev-cadence and runs it from a cache instead of carrying 41 synced files — which removes most of
what requiring it would cost a repo.

## Options

1. **Keep dev-cadence optional (do nothing).** Keeps a path no repo here uses, every slot's absent-seam
   sentence, `ao repo init`, and the silent fallbacks, each a branch to keep right. The person's texts get a
   second, ShiftLead-only home.
2. **Make the cadence pluggable** — an interface any process could implement, dev-cadence the first. One
   implementation and no second in view; the interface would be shaped by the one. Rejected.
3. **Merge dev-cadence into ShiftLead.** Ends the standalone cadence, which ADR 2026-10-12 kept for
   sessions and people with no orchestrator. Rejected.
4. **ShiftLead requires dev-cadence; dev-cadence stays usable alone; the person's ShiftLead texts live in
   their dev-cadence layer repo.** The dependency runs one way. **Recommended.**

## Decision

Proposed: **4**, as two questions for Paul, since the second stands without the first:
- **Q1.** ShiftLead requires dev-cadence in every repo it serves?
- **Q2.** The person's briefs, start prompts and preferences live in a `shiftlead/` directory of their
  dev-cadence layer repo, as additions to the package's text? With two sub-questions, each with a
  recommended answer below: **Q2a**, what a layer followed from someone else contributes (*Decision* 7);
  **Q2b**, whether the home commits into the person's layer clone (*Decision* 10).

**Q1 — what requiring it means.**

1. **Adoption is a PR the person sees.** Registering a repo with ShiftLead (today a line in the home's `repos.txt`, design §5; a new
   `ao repo` word for it is part of the build) offers, for a repo with no dev-cadence, to adopt it:
   it shows what dev-cadence's adopt writes (the seeds and, under the companion plan, the pin; today
   `sync.sh`'s files) and, on the person's yes, opens that as a PR in the repo, as any change lands —
   never a push, and never written silently. ShiftLead serves the repo once the adoption merges. A repo
   whose owners will not take the PR is not served (*Revisit triggers*). The adopt is dev-cadence's
   command, never ShiftLead's code.
2. **What changes in the design and the 2026-10-12 ADR.**
   - *recommends dev-cadence and requires only a ledger* (design §8; 2026-10-12's *Requires: a ledger*) → *requires dev-cadence*.
   - §5 *The seams*: the cadence's own seams are fixed to dev-cadence. `gate:` goes — the gate is
     `check_cadence.py`, and a repo's extra check is dev-cadence's precheck (cadence §4.12). The slots'
     absent-seam sentences for `{gate}`, `{board}`, `{ledger_check}` and `{cadence_rules}` go; §5's *a repo
     without dev-cadence is a repo like any other* and *a repo with a board needs no dev-cadence* go.
   - A refusal, naming the adopt (today the sync), is kept for what ShiftLead cannot supply itself: no pin (or lock), no
     gate, no ledger. The SessionStart line is not among them — ShiftLead's launch already carries it for
     every session it starts (`CADENCE_HOOK_LINE`) — so a repo whose own settings lack it gets a Repo-page
     warning at most.
   - `ao repo init` goes.
   - **Kept:** the slots for the repo's own commands (`{test}`, `{lint}`, `worktree_setup:`) and their
     sentences — they are the repo's, not the cadence's; the three layers; ledgerboard as the formats' one
     home; ADR 2026-10-08's rule that a dev-cadence file never calls `ao`.
3. **How ShiftLead's readers find dev-cadence's code.** Today several readers each read a path in the
   checkout. While the copy stands they keep doing so. Under the companion plan every one asks **one
   resolver** for **the command to run** — its argv and environment, `CADENCE_REPO_ROOT` included — so no
   reader sets that up itself. The resolver calls the launcher, which is a dependency of ShiftLead's install
   (the host agent finds it in its own venv, never on a login `PATH`, and it is pinned by the wheel, so a
   rollback of the live copy covers it). A container node has no network path to a private dev-cadence and
   no lasting cache, so the home ships the pinned trees a node needs with the wheel (`ao host up`). A repo
   whose pin cannot be resolved is refused by name, never skipped — including a pin that needs a newer
   launcher interface than ShiftLead's, which a ShiftLead release cures (the breaking change *Decision* 4
   has dev-cadence wait on).
4. **Which dev-cadence ShiftLead works with.** ShiftLead names the oldest dev-cadence commit it reads and the
   launcher interface it needs, and refuses an older pin by name (under the copy, the lock's `files_commit`
   is checked the same way). The newer side is dev-cadence's promise: the `--json` shapes and fields
   ShiftLead reads, which cadence §7's parity table names, change only additively, and a breaking change
   waits for a ShiftLead release that reads it, with its `cadence-changes.md` entry saying so.
5. **TD-681 is replaced, not trimmed.** Under the companion plan there is no lock and no copied file to
   replay. The home's check of a bump proves the PR changes only the pin lines of `docs/cadence.toml` (the plan's
   *Decision* 1: the `ref` line and its tag comment), that
   `ref` is a full commit on the unchanged source's default branch, and that it descends from the old pin;
   it merges only on review evidence whose reviewer read the compare (the plan's *Decision* 7). A bump that
   changes `source` or anything else in the repo is refused by name as not routine, and is the person's to
   merge. Its own build entry.
6. **ledgerboard** is pinned by its header on both sides: the wheel's copy and dev-cadence's are each
   vendored from a tagged release whose name and hash head the file, so parity no longer depends on a synced
   copy in the repo, and the home warns when a served repo's pinned tree vendors a different release.

**Q2 — the person's home for their texts.**

7. **One personal home: the person's dev-cadence layer repo.** It gains a `shiftlead/` directory at its
   root, beside the cadence rules (for Paul, `~/cadence-layer/shiftlead/`): `preferences.md` (the
   director's, TD-657 — moved there from `~/.shiftlead/` before TD-662 builds it), `briefs/<role>.md` (the
   person's additions to a role's brief), `entry.md` and `work.md` (their additions to the start context
   and the first prompt). ShiftLead finds the layer repos through dev-cadence's reader (`cadence_layer.py`),
   never a setting of its own: the root of the git repo that holds each layer's file, read from the working
   tree for one's own layer and at the pinned `ref` for someone else's. They are read at the home, from the
   home machine's `cadence.toml`, and never on a node. **Q2a, recommended:** a followed layer contributes
   brief, entry and work additions — prose the person chose to follow, like that layer's cadence rules — but
   never `preferences.md`, which decides on the person's behalf and is read from their own layer alone, so
   §4.9b's floor (*Always ask me*, the Never list) stays the person's. With no layer set, ShiftLead uses the
   package's texts alone and points at dev-cadence's setup step; it writes nothing to `~/.shiftlead/` in its
   place. ShiftLead reads the `shiftlead/`
   files itself; dev-cadence adds what that needs and no more — a `--json` listing of
   each layer's repo root and kind (one's own, or followed at a pin, with its `ref`), which the home runs
   through the resolver under the session's repo, so the reader is that repo's pinned one, since ShiftLead cannot import the
   reader from a pinned tree, and one line saying a tool may keep a directory of its own in a layer repo,
   which dev-cadence never reads (dev-cadence TD-132) (its publish check, which reads every tracked file, covers it too).
   `~/.shiftlead/` keeps what belongs to this install (`org.yml`, `profiles.yml`, `settings.yml`).
8. **Additions, never replacements, in one order.** The texts are joined in this order — the package's,
   then the person's layer, then the repo's (`.shiftlead.yml`, a definition's `brief:`) — and the session is
   told that where they disagree the later wins, as the cadence (cadence.md → layer → the repo's CLAUDE.md)
   and the designed preferences already say. Nothing is replaced mechanically.
   A person's brief text is filled into a slot of its own beside *This repo's rules*, under the same
   sentence; no layer replaces a whole brief or heading (§4.8: a copied brief goes stale and wins over the
   template's current mechanics), and none takes from a *never* list or moves a host-agent gate.
9. **Where it shows.** A session reads its texts at start, so an edit applies to the next start (a team
   member by §6 rule 7's restart, as a brief change does now). The Session card's *told at start* row
   (TD-993) names each part's source — the package, a layer and its commit, the repo.

10. **Q2b — who writes the layer, recommended: the home commits, the person pushes.** The director's
   *Accept*, *Remember this* and groom pass (TD-663) write `preferences.md`. With it in the layer, the home
   commits to the person's clone of their layer repo and never pushes; the layer reader's *unpushed* and
   *behind* lines (TD-126) tell the person to push or pull. The home refuses a write, naming why, while that
   file has uncommitted edits or the clone is behind its upstream, so it never writes over an edit made on
   another machine.

## Consequences

- ShiftLead's release waits on dev-cadence being publishable: TD-090's scrub, and TD-128 moving the
  owner's preferences out of the shared cadence.
- Q1 holds without the companion plan, at the cost of the synced files in every served repo; with it,
  adoption is a pin, the seeds and one wiring line. Q2 holds with either answer to Q1.
- dev-cadence never calls `ao`, never reads `shiftlead/`, and stays usable with no ShiftLead on the
  machine (ADR 2026-10-08's rule and ADR 2026-10-12's goal, both kept).
- **Harder:** serving a repo whose owners do not use the cadence — they must take the adoption PR or go
  unserved.
- Builds follow the decision, each its own entry, after design §4.7, §4.8, §4.9, §4.9b, §5, §6 and §8
  change: (Q1) the adoption offer when a repo is registered; the refusals in place of the fallbacks, with the seams,
  sentences and `ao repo init` removed; the one resolver and the readers moved onto it (with the
  companion plan's build); the oldest-commit check; TD-681's replacement; the ledgerboard header check;
  (Q2) dev-cadence's `--json` listing of layer roots; the `shiftlead/` layer reader and the brief, entry
  and work additions; the home's commits into the layer clone (Q2b, with TD-663); TD-657's preferences moved
  before TD-662; the Session card row's sources (with TD-993).
- Out of bounds once decided: a repo served without dev-cadence (Q1), and a second home for the person's
  ShiftLead texts (Q2).

## Revisit triggers

- A person or team asks to run ShiftLead under another process, or on a repo whose owners will not take the
  adoption PR, and that is what stops them.
- dev-cadence needs to call ShiftLead to do its job (the dependency would no longer run one way).
- The layer repo needs something only ShiftLead can provide (a server, a database), so the person's texts
  outgrow a git repo.

## Review

- **Round 1 (Sonnet, 2026-10-25, both documents): NOT READY — 5 BLOCK, 7 FIX, all adopted.** Here: how
  ShiftLead's readers find the pinned code (*Decision* 3); TD-681 replaced, not shrunk (5); the full list of
  what changes in 2026-10-12 and §5, `gate:` included (2); what *version* means with no versions (4);
  ledgerboard's parity anchor (6); adoption as a PR the person sees, and a repo that will not take it (1);
  the question split in two; *on this machine's roster*.
- **Round 2 (Fable, 2026-10-25): NOT READY — no BLOCK; 4 FIX and 4 NOTE here, all adopted.** A followed
  layer's preferences (Q2a) and the home's commits into the layer (Q2b) made questions for Paul, each with a
  recommendation; the resolver returns the command and its environment, not a path; refusals only for what
  ShiftLead cannot supply (the SessionStart line is a warning); nodes get their trees from the home and read
  no layer; the newer-pin side is dev-cadence's additive promise; the precedence wording (joined in order,
  the later winning, nothing replaced); the readers' list and the parity mechanics left to the build.
- **Round 3 (Sonnet, 2026-10-25): NOT READY — no BLOCK; 2 FIX and 2 NOTE here, all adopted.** *The pin
  lines* as the plan defines them; the ledger entry's Fix lists every build named here; dev-cadence's
  `--json` listing of layer roots named as the one interface Q2 needs from it; *naming the adopt*; *several
  readers*.
- **Round 4 (Fable, 2026-10-25): READY — 2 NOTE, both adopted.** The layer listing run through the resolver
  under the session's repo and carrying a followed layer's `ref`; a pin needing a newer launcher interface
  is cured by a ShiftLead release. Sonnet's round 3 had said READY once its fixes were in; the two
  reviewers agree.
