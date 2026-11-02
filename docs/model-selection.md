# Model selection

Siesta keeps the committed role defaults in factory/config/models.json.
Choose project-local routes with a JSON file passed to the CLI:

~~~json
{
  "phases": {
    "interview": {"model": "qwen3:latest", "provider": "ollama"},
    "planning": {"model": "glm-5.2:cloud", "provider": "ollama"}
  },
  "agents": {
    "planning": {
      "planner": {"model": "glm-5.2:cloud", "provider": "ollama"}
    }
  }
}
~~~

Each route requires an exact model and provider. An agent route applies only to
that agent in that phase. Siesta resolves routes in this order:

1. Agent route within the selected phase.
2. Phase route.
3. The project's saved snapshot of the configured planner, worker and
   consultant routes.

The available phase keys are interview, intent_review, specification, planning,
design_review, design_repair, implementation, issue_review, review, verification,
completion, learning, iteration_specification and iteration_planning. Agent keys
are the registered agent IDs.

Start with a selection file:

~~~bash
python3 -m pipeline --auto --model-selection local-models.json "Build a small CLI"
~~~

The effective configuration is saved in the project's ignored evidence at
.siesta/model-selection.json. Resuming without --model-selection reuses that
saved selection and its role-default snapshot. Passing a new selection file
replaces the project selection for that run. Model configuration files contain
model identifiers only; provider credentials stay in the existing Pi/Ollama
configuration.

The local desktop API accepts the same object as model_selection when it starts
a run. The browser controls are added separately in issue #15.
