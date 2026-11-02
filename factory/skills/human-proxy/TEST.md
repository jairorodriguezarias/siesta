# Human Proxy Scenarios

Run the YAML cases from the repository root with:

    PYTHONPATH=factory python -B -m pipeline.evaluate --output .runtime/human-proxy-scenarios --skill-scenarios factory/skills/human-proxy/test_scenarios.yaml

This runs format validation and the deterministic response fixtures. Add
--real-skill-scenarios to send the same prompts to the configured consultant
model. Live wording can differ, so the assertions check the decision marker
and relevant cited evidence rather than a full response transcript.

Each prompt supplies the original intent, recorded decisions, specification,
request and relevant context. Keep these inputs together when adding cases so
the reviewer is tested against actual scope evidence. Scenarios cover approval,
rejection, missing information and a fenced approval example. The last case
must remain unapproved because only markers outside fenced examples count.

The proxy runs without tools. If a response claims it ran a command, inspected a
file or performed another tool action, the evaluator requires a structured
execution log; a prose claim is not evidence.
