# Getting started

Siesta is intended for small applications that run on your computer. Start
with one observable behavior and require tests in every implementation issue.

## Install

You need Python 3.10+, Git, Bash, a Node.js version supported by Pi, and Ollama.
From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
pi --help
ollama list
```

Configure your Git name and email so generated projects can create commits.
Keep the Python environment active while running Siesta. The runtime itself
uses the standard library; pytest checks generated Python projects.

## Configure models

Edit [`factory/config/models.json`](../factory/config/models.json):

| Role | Responsibility | Committed default |
| --- | --- | --- |
| Planner | Interview, specification and plan | `glm-5.2:cloud` |
| Worker | Implementation, code review and verification | `gemma4:31b-cloud` |
| Consultant | Design/evidence review, advice, proxy and learning | `glm-5.2:cloud` |

The defaults use **Ollama Cloud**, proxied through your local Ollama daemon.
Configure access before running. Register models in Pi with their actual
context windows. For inference on your own machine, use the
[local Ollama guide](ollama-local.md).

Independent reviewers require Pi's `--no-context-files`, `--no-extensions`,
`--no-skills`, `--no-prompt-templates` and `--no-session` options. Check `pi --help`;
the live evaluation record identifies the version tested.

## Run

```bash
./factory/bin/siesta.sh 'Build a small Python CLI timer with tests'
```

Answer the interview in the terminal. Confirm the final intent with `yes`, or
type `auto` to delegate the remaining decisions. For a detailed request:

```bash
./factory/bin/siesta.sh --auto \
  'Build sum_cli.py: accept two integers, print their sum, reject invalid input. Use one issue with pytest tests.'
```

The specification records acceptance bullets such as `- R1: Print the sum of
two integers.` Two independent readers review the intent, spec and plan before
implementation. After implementation, Python reruns tests and the evidence
reviewer checks each criterion against real passing test IDs and source.

## Resume or stop

Relaunch the same command to resume. `--resume` is accepted but optional:

```bash
./factory/bin/siesta.sh --auto --resume 'the exact original idea'
```

Place `stop.md` in the generated project to stop at startup or the next issue
boundary. Remove it before resuming. A clean stop exits successfully but does
not mean the project completed.

If design review fails, inspect `.siesta/design-review.md`, revise `spec.md` or
`issues.md`, commit the edits in the generated project, then resume. Completed
issue requirements are immutable: add a new issue instead of rewriting one.
Uncommitted product changes at resume are preserved and require your attention.

If requirement verification fails, inspect `.siesta/requirements.md` and
`regression_0.log`. Fix the product or its tests, commit, and resume. Changes to
a reviewed product invalidate the recorded review and verification.

## Local data

Generated projects, transcripts and learning stay under `factory/` and are
ignored by the Siesta repository. `SIESTA_FACTORY` selects another factory;
`PI_CODING_AGENT_DIR` selects an isolated Pi profile. `SIESTA_PI_TIMEOUT` bounds
each model call in seconds (default: 1200).

Changing the factory alone does not change where model inference runs. Worker
tools have your process permissions; context isolation is not an OS sandbox.
