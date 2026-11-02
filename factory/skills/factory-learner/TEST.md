# Factory Learner Scenarios

Run the fixtures from the repository root with:

    PYTHONPATH=factory python -B -m pipeline.evaluate --output .runtime/factory-learner-scenarios --skill-scenarios factory/skills/factory-learner/test_scenarios.yaml

The cases cover a complete supported proposal, an incomplete replacement,
contradictory test evidence and an outcome with no reusable evidence. The
complete proposal preserves verification ownership, tool limits and literal
examples. Its assertions reject a weakened test gate or an invented tool.

The development tests also send complete candidates through the proposal
recorder and confirm that the active skill remains unchanged. Proposal
activation belongs to a separate review and validation step.
