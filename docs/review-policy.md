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

| Policy | Maximum rounds | Maximum repairs | Clean rounds required |
|---|---:|---:|---:|
| Normal | 3 | 2 | 1 |
| Deep | 5 | 2 | 2 consecutive rounds on the same version |

The review ledger fixes its policy and author at creation. A repair records its
old and new version identifiers, the findings it addresses, a repair evidence
note and the checks that must run again. Each required check needs a passing
result with evidence before another review round can start. Failed check
results remain in the ledger.

An author may attach counterevidence to a finding. It cannot dismiss the
finding: an independent adjudicator must record an evidence-based upheld or
dismissed decision. An adjudicator also gets at most one retry. Dismissing all
findings requires a fresh clean review round before approval.

The module provides these gates; issue-level and final-review integrations are
added in the following review issues.
