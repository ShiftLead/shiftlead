# Second pass: the pattern behind each design-review finding

Each line of your input file is one finding a reviewer raised on a software design plan (shiftlead: a dashboard that orchestrates AI coding-agent sessions in tmux across hosts, with a host agent, a ledger of work entries, an attention board, mail between sessions, teams and seats). A first pass already labelled each row:
`kind` (what was wrong), `origin` (`original` or `fix-induced`), `catch` (where it would otherwise be caught), `area`.
The `finding` text is often written as the resolution (what the design says after the fix); read `topic`, `finding` and `status` together to infer what was missing or wrong.

Your job is to name the pattern, so the patterns can become (a) a checklist an author answers before drafting, (b) the checks of a script, (c) the facts an author must verify first. Judge every row by reading it. Do NOT write a keyword or regex classifier; a script may only read the input in chunks and append your labels. Use only the rows. Take the first pass's labels as given. When a row does not let you tell, use `other`.

Output one JSON object per input row, same order, with exactly these keys (use "-" where a key does not apply):

- `id`: copied.
- `case` — only when `kind` is `unspecified`, `wrong-mechanism` or `contradiction`; else "-". The situation the design had not handled, one of:
  - `restart`: a process or agent restart, crash, replay, resume, or a promote/upgrade partway.
  - `concurrency`: two actors or events at once; a race; the order of two events; what a tick sees mid-change.
  - `multi-node`: a node versus the home, another host or container, a link down, another repo or team's home.
  - `empty-first`: nothing there yet: first run, missing record or file, old data from before the change, migration.
  - `ends`: the thing goes away or changes identity: closed, archived, deleted, renamed, expired, wound down, superseded.
  - `failure`: an error path: a command fails or is refused, a timeout, a partial write, an unreadable input.
  - `who`: which actor does it, may do it, or is told; identity and permission.
  - `when`: the trigger or timing: exactly when, how often, until when, by which clock.
  - `which`: choosing among several: which record, newest, tie-break, precedence or order among rules.
  - `shape`: the data's shape: field, format, name, where it is stored, the exact words of a text or output.
  - `display`: what a screen or command shows in some state; a state not drawn.
  - `scope`: what the rule covers or excludes; its boundary; whether it applies to other kinds, repos, teams.
  - `interaction`: how it combines with an existing rule or feature elsewhere in the system.
  - `proof`: how it is verified: the test, the Done when, the live check.
  - `other`.
- `q` — only when `case` is not "-"; else "-". The general question the author should have answered, at most 12 words, phrased so it applies to other designs too (e.g. "What does the tick do if the record is missing?" not names of this design's functions).
- `fact` — only when `kind` is `false-claim`; else "-". What sort of fact was wrong, one of:
  - `code-behaviour`: what existing code does.
  - `code-exists`: whether a function, file, flag, field or test exists, or its name.
  - `design-text`: what another section, the glossary or another doc says.
  - `work-state`: what is built, merged, live, or which entry or PR did it.
  - `data`: a number or measurement.
  - `external`: how an outside tool behaves (Claude Code, git, gh, tmux, the forge).
  - `other`.
- `check` — only when `catch` is `mechanical`; else "-". The check a script would run, one of:
  - `section-ref`: a section number, heading or anchor that should resolve.
  - `id-ref`: a TD id, PR number or finding id that should exist or be in the right state.
  - `path-symbol`: a file path, function, flag or field name that should exist in the code.
  - `duplicate-text`: the same statement made in two places that have drifted apart.
  - `entry-fields`: a ledger entry's fields, parts, Done when or review record out of step with the design.
  - `count`: a count or list that can be recomputed.
  - `format`: a template or format rule.
  - `other`.
- `fixfail` — only when `origin` is `fix-induced`; else "-". Why the earlier fix led to this finding, one of:
  - `not-propagated`: the fix was made in one place and another place still said the old thing.
  - `new-gap`: the fix introduced a new case and left it open.
  - `wrong-fix`: the fix's own mechanism was wrong.
  - `overreach`: the fix changed or contradicted something that was right.
  - `incomplete`: the fix addressed only part of the finding.
  - `other`.

Output rules: append to the output file in chunks of at most 80 rows as you go; valid JSON Lines; nothing else in the file. Keep any helper script in a directory of your own named after your batch (given below), never in a shared directory. When done, verify with a short script: as many lines as the input, every line parses, ids match in order, every value allowed, and each key is "-" exactly when its condition says so; fix what fails. Do not run any `ao`, `git` or `gh` command and write nothing outside your own directory and output file.

Final report (under 120 words): row count, verification result, and up to three patterns the labels will not show.
