# ADR 2026-10-25: ShiftLead requires dev-cadence, and the person's own texts live in their dev-cadence layer

**Status:** proposed — for Paul's decision (drafted with him, 2026-10-25, session `ao-shiftlead-prompts`)
**Date:** 2026-10-25
**Supersedes, if decided:** in [ADR 2026-10-12](2026-10-12-ledgerboard-dev-cadence-shiftlead.md), the layer
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
  dev-cadence layer repo, as additions to the package's text?

**Q1 — what requiring it means.**

1. **Adoption is a PR the person sees.** `ao repo add` on a repo with no dev-cadence offers to adopt it:
   it shows what dev-cadence's adopt writes (the seeds and, under the companion plan, the pin; today
   `sync.sh`'s files) and, on the person's yes, opens that as a PR in the repo, as any change lands —
   never a push, and never written silently. ShiftLead serves the repo once the adoption merges. A repo
   whose owners will not take the PR is not served (*Revisit triggers*). The adopt is dev-cadence's
   command, never ShiftLead's code.
2. **What changes in the design and the 2026-10-12 ADR.**
   - *ShiftLead requires only a ledger* (2026-10-12's section, design §8) → *requires dev-cadence*.
   - §5 *The seams*: the cadence's own seams are fixed to dev-cadence. `gate:` goes — the gate is
     `check_cadence.py`, and a repo's extra check is dev-cadence's precheck (cadence §4.12). The slots'
     absent-seam sentences for `{gate}`, `{board}`, `{ledger_check}` and `{cadence_rules}` go; §5's *a repo
     without dev-cadence is a repo like any other* and *a repo with a board needs no dev-cadence* go.
   - Convention notices and the SessionStart line, *features of one, not requirements* in 2026-10-12,
     become requirements: a missing one is a refusal naming the sync, not a silent skip.
   - `ao repo init` goes.
   - **Kept:** the slots for the repo's own commands (`{test}`, `{lint}`, `worktree_setup:`) and their
     sentences — they are the repo's, not the cadence's; the three layers; ledgerboard as the formats' one
     home; ADR 2026-10-08's rule that a dev-cadence file never calls `ao`.
3. **How ShiftLead's readers find dev-cadence's code.** Today each reads a path in the checkout:
   `sessionorc/cadence.py` (the gate), `sessionorc/agent_ids.py` (`ledger_next_id.py`), `repoconfig.layout`
   (which `scripts/*` exist), `worktree_setup`'s default (`hydrate_worktree.sh`), `doctor.py`,
   `conventions.py`, `ui/inbox.py` (`nudge_user_attention.py --report`), `sessionorc/sync.py` (the lock) and
   the Claude Code adapter's `CADENCE_HOOK_LINE`. While the copy stands they keep doing so. Under the
   companion plan, every one asks one function, `cadence.script(repo, name)`, for the path: it calls the
   launcher's resolve (the launcher is a dependency of ShiftLead's install, so the host agent finds it in its
   own venv, never on a login `PATH`; a container node gets it with the wheel, `ao host up`), which ensures
   the pinned tree. A repo whose pin cannot be resolved is refused by name (*no dev-cadence at the pinned
   commit: <why>*), never skipped. The hook line becomes the seed's `dev-cadence hook session-start`.
4. **Which dev-cadence ShiftLead works with.** ShiftLead names the oldest dev-cadence commit it reads and the
   launcher interface it needs. The home checks a repo's pin descends from that commit (`git merge-base
   --is-ancestor`, in the cache's clone) and refuses an older pin by name; under the copy, the lock's
   `files_commit` is checked the same way.
5. **TD-681 is replaced, not trimmed.** Under the companion plan there is no lock and no copied file to
   replay. The home's check of a bump proves the PR changes only the pin lines of `docs/cadence.toml`, that
   `ref` is a full commit on the source's default branch, and that it descends from the old pin; it merges
   only on review evidence whose reviewer read the compare (the plan's *Decision* 7). Its own build entry.
6. **ledgerboard.** The wheel's `src/sessionorc/ledgerboard.py` is vendored from a tagged ledgerboard
   release, as dev-cadence's is, its first line naming the release and hash; the parity test checks that
   line against the file, not against a synced `scripts/ledgerboard.py` the repo will no longer hold. The
   home warns when a served repo's pinned tree vendors a different release from the wheel's.

**Q2 — the person's home for their texts.**

7. **One personal home: the person's dev-cadence layer repo.** It gains a `shiftlead/` directory at its
   root, beside the cadence rules (for Paul, `~/cadence-layer/shiftlead/`): `preferences.md` (the
   director's, TD-657 — moved there from `~/.shiftlead/` before TD-662 builds it), `briefs/<role>.md` (the
   person's additions to a role's brief), `entry.md` and `work.md` (their additions to the start context
   and the first prompt). ShiftLead finds the layer repos through dev-cadence's reader (`cadence_layer.py`),
   never a setting of its own: the root of the git repo that holds each layer's file, read from the working
   tree for one's own layer and at the pinned `ref` for someone else's. ShiftLead reads the `shiftlead/`
   files itself; dev-cadence documents only that a tool may keep a directory of its own in a layer repo,
   and never reads it (its publish check, which reads every tracked file, covers it too).
   `~/.shiftlead/` keeps what belongs to this install (`org.yml`, `profiles.yml`, `settings.yml`).
8. **Additions, never replacements, in one order.** The package's text, then the person's layer, then the
   repo's (`.shiftlead.yml`, a definition's `brief:`), the more specific winning where they disagree — the
   order the cadence (cadence.md → layer → the repo's CLAUDE.md) and the designed preferences already use.
   A person's brief text is filled into a slot of its own beside *This repo's rules*, under the same
   sentence; no layer replaces a whole brief or heading (§4.8: a copied brief goes stale and wins over the
   template's current mechanics), and none takes from a *never* list or moves a host-agent gate.
9. **Where it shows.** A session reads its texts at start, so an edit applies to the next start (a team
   member by §6 rule 7's restart, as a brief change does now). The Session card's *told at start* row
   (TD-993) names each part's source — the package, a layer and its commit, the repo.

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
  change: (Q1) the adoption offer in `ao repo add`; the refusals in place of the fallbacks, with the seams,
  sentences and `ao repo init` removed; `cadence.script()` and the readers moved onto it (with the
  companion plan's build); the oldest-commit check; TD-681's replacement; the ledgerboard header check;
  (Q2) the `shiftlead/` layer reader and the brief, entry and work additions; TD-657's preferences moved
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
