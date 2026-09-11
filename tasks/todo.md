# Reliability and local run checklist

- [x] Verification: false model approval cannot override red/absent tests; real suite evidence recorded.
- [x] Retry gates: empty/degenerate/unresolved outputs block on every recovery path.
- [x] Review: fixes undergo a new review; missing approval stops advancement.
- [x] Interview: a real silent/open-pipe child times out and partial output survives.
- [x] Cleanup: staged and new product files disappear from working tree/index; KB and recovery survive.
- [x] Resume: pending issues retry after later checkpoints; completed issues remain idempotent.
- [x] Full tests and five-axis review pass; docs explain corrected behavior.
- [x] Local provider: actual model identity, tool call round-trip, served context verified.
- [x] Four distinct full pipeline runs recorded with independent product checks.
- [x] Report results and remaining limitations with evidence.

Closed 2026-09-11: 215 factory tests; four completed local projects;
62 product tests and 14 independent contract checks.
See [the validation report](reliability-validation-20260911.md).
