# Review policy

The shared persistence and policy layer is pipeline.reviews.ReviewSession.
It stores state in .siesta/reviews/<review-id>.json; the ignored evidence
survives project resumes and does not enter product source prompts.

## Reviewer report

A reviewer returns one JSON object with exactly these fields:

~~~json
{
  "version": 1,
  "verdict": "findings",
  "summary": "The input validation misses the empty value.",
  "findings": [
    {
      "id": "F1",
      "severity": "major",
      "target": "R2 / app.py:12",
      "evidence": "The empty input reaches the parser and raises an exception.",
      "requested_fix": "Return the documented empty result."
    }
  ]
}
~~~

The verdict is pass, findings or insufficient_evidence. Findings require a
unique ID, severity (critical, major, minor or info), requirement or location,
evidence and a requested correction. A pass cannot contain findings; an
insufficient-evidence response cannot be treated as approval.

Before each reviewer call, the pipeline records the agent and a context
manifest with included and omitted paths. An empty included list is rejected.
One failed or invalid reviewer call permits one retry. A report that asks for
more evidence can be retried once only after the manifest expands; that uses
the same retry slot. Raw valid and invalid reviewer responses are retained in
the ledger; oversized responses keep a preview, character count and SHA-256.

## Policies and repairs

| Policy | Maximum rounds | Maximum repairs | Clean rounds required | Calls | Active minutes |
|---|---:|---:|---:|---:|---:|
| Normal | 3 | 2 | 1 | 20 | 60 |
| Deep | 5 | 2 | 2 consecutive rounds on the same version | 40 | 120 |

The review ledger fixes its policy and author at creation. A repair records its
old and new version identifiers, the findings it addresses, a repair evidence
note and the checks that must run again. Each required check needs a passing
result with evidence before another review round can start. Failed check
results remain in the ledger.

The policy is chosen before a project starts with `--review-policy` or in the
desktop and saved in `.siesta/review-policy.json`. Its budget persists on
resume. Reviewer attempts, retries, worker repair calls, proxy calls and
adjudications all spend calls. Active time is measured around those calls;
waiting for user input or between runs does not spend active minutes. When a
limit is exhausted, the review blocks. Token and cost data remain unknown when
Pi does not supply trustworthy totals.

An author may attach counterevidence to a finding. It cannot dismiss the
finding: an independent adjudicator must record an evidence-based upheld or
dismissed decision. An adjudicator also gets at most one retry. Dismissing all
findings requires a fresh clean review round before approval.

## Final product review

The final review uses two required, isolated agents: `integration-reviewer`
checks requirements and integration, and `quality-reviewer` checks concrete
code defects and quality. Each receives the approved contracts, source, test
results and an included/omitted context manifest. They do not receive author
history or informal justifications, and Pi tools are disabled for both.

Both specialists must return valid passing reports before the human-proxy can
approve. The proxy receives both reports plus intent and recorded decisions.
Proxy rejection becomes a repairable finding. A repair must preserve the
requirements, change the product version and pass the regression suite before
it is committed and reviewed again.

Review evidence and call metrics are stored in `.siesta/`. The approval is
bound to the product content and the review configuration, including selected
routes, specialist definitions, proxy instructions and the Definition of Done.
A resume reuses approval only when both fingerprints match. Test results,
including a failing regression log, are shown to the specialists; final
verification still determines whether delivery is verified or `UNVERIFIED`.

## Issue review

After an issue's product tests pass, Siesta opens an independent review before
writing the completion record. The integration reviewer receives the
specification, only the active issue text, the diff from its committed base,
source and test evidence, a context manifest, and committed records for earlier
completed issues. Later issue descriptions, worker output and informal author
history are excluded. A finding repair stays uncommitted until the issue is
approved; a rejected issue is archived and restored to its committed base.

Issue bodies may declare `Review: standard` or `Review: extended`. Standard
review requires the integration reviewer. Authentication or authorization,
migrations, and public APIs or interfaces require the extended declaration;
design validation rejects a sensitive issue marked standard. Extended review
also requires the independent quality reviewer. Both modes use the project's
chosen bounded policy and rerun the product regression suite after each repair. Issue
review approval is bound to the active issue, committed base, product content,
reviewer definitions and model routes.
The final specialist review runs only after all implementation issues have
completed. A blocked issue remains unverified and is retried on resume;
reviewers are not asked to approve its recovered, incomplete product tree.

## Intent review

At interview closeout, `intent-critic` independently compares the original
request and explicit human answers with the candidate intent. The transcript
provides context, but rejected summaries do not count as decisions. A proposed
correction must quote an exact substring from the request or an explicit
answer. Python validates the strict report and saves it in
`.siesta/intent-review.json`. A report that needs a new user decision records a
KB blocker and stops before specification generation. Interactive confirmation
is retained as interview evidence.

## Design review and repair

Before implementation, three tool-free agents independently check
comprehension, simplicity and implementation readiness against the approved
intent, specification and issue plan. Python also requires every acceptance ID
to appear in an issue with a nonempty `Test strategy:` line, and checks that
dependencies refer only to earlier issues that exist. Sensitive issues must
declare extended review.

Blocking findings may invoke the planner with only the approved intent, current
documents and findings. It can return complete replacement documents, but
Python rejects changed acceptance criteria, invalid coverage or dependencies,
and edits to completed issue bodies. A valid revision is recorded, written and
committed before the three reviewers run again. The design gate allows at most
three review rounds and two repairs; each reviewer gets one retry for an
invalid or failed response. Its local ledger preserves the attempts and repair
commits across resumes. Approval is tied to document bytes, agent definitions
and selected routes.
