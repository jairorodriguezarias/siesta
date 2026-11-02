# Issue Executor Scenarios

Run the deterministic protocol and response fixtures from the repository root:

    PYTHONPATH=factory python -B -m pipeline.evaluate --output .runtime/issue-executor-scenarios --skill-scenarios factory/skills/issue-executor/test_scenarios.yaml

The suite covers implementation with recorded file and test actions,
consultation, approval requests, implementation after guidance, and a repeated
consultation that leaves the issue blocked. A report that says it ran tests
without an execution record fails the tool-evidence assertion.

The factory tests also create a temporary project, run a real pytest process,
and inspect the passing test ID persisted by Python. The end-to-end recovery
tests run the pipeline against real Git and project tests, then check that the
worker did not rewrite the specification or issue plan. Pi text output does not
expose structured tool events, so live skill evaluation cannot by itself prove
that a worker executed its claimed commands.
