# The fact-checker's planted-defect runs

One row per run of `pdm run judge fact-checker --profile <p>` (design §4.9b *A model's fitness, before the role*,
TD-1649): the date, the profile, the `<adapter>/<model>` the first answered case's reply names (`—` where no case
was answered), the defects caught and missed in the answered cases, the false findings, the cases `none`, the
run's minutes from its first create to its last case's end, and whether it passed the bar. The set is
`tests/judgment/fact-checker/`, and its README says how a reply is scored.

The first row is not a run. It is the Gemini fact-check trial's own tally to 2026-11-10 (TD-1214): four verdicts,
0 caught, 9 missed, and 63 of 72 lines `none`.

| date | profile | model | caught | missed | false | none | minutes | passed |
|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | gemini-reader | — | 0 | 9 | — | 63 of 72 | — | not a run |
| 2026-11-14 | grok-reader | grok/grok-4.7 | 11 | 0 | 0 | 0 | 60 | yes |
