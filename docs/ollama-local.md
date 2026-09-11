# Run Siesta with local Ollama models

This setup runs all three roles through a local Ollama daemon. The checked-in
[routing template](../factory/config/local-ollama.example.json) selects the
`siesta-local:latest` alias; the [Pi catalog](../factory/config/pi-ollama.example.json)
connects it to `http://localhost:11434/v1`. Choose the underlying model yourself.
The same model must support both native tool calls and the text protocols used
by the planner, consultant, proxy and learner.

Model suitability must be checked through real tool use and a complete project.
See [testing](testing.md) for the acceptance checks and their limits.

## Prerequisites

- Python, pytest and Git, as described in the [README](../README.md#installation).
- Pi installed and available as `pi` on `PATH`.
- Ollama running locally, with a downloaded model suitable for tool use.
- Enough memory for the chosen model and context size.

From the repository root, inspect the installed models with `ollama list`.
Select a local model tag, without a `:cloud` suffix. Check its capabilities
with `ollama show MODEL_TAG`; advertised tools support still needs the real
Pi probe below.

## Create an isolated profile

Run these commands once from the repository root in Bash. An existing profile
is left intact; choose a new directory if you want another fresh profile.

```bash
test ! -e .runtime/ollama-local || { echo 'Profile already exists'; exit 1; }
mkdir -p .runtime/ollama-local/factory/config .runtime/ollama-local/factory/kb .runtime/ollama-local/pi
mkdir -p .runtime/ollama-local/.agents
cp factory/kb/global-seed.json factory/kb/schema.json .runtime/ollama-local/factory/kb/
cp -R factory/skills .runtime/ollama-local/factory/
cp -R .agents/skills .runtime/ollama-local/.agents/
cp factory/config/local-ollama.example.json .runtime/ollama-local/factory/config/models.json
cp factory/config/pi-ollama.example.json .runtime/ollama-local/pi/models.json
printf '%s\n' '{"packages": [], "quietStartup": true}' > .runtime/ollama-local/pi/settings.json
```

The copied seed supplies standing principles without importing prior run history.
Projects, learned skill changes
and Pi state stay in this Git-ignored profile. Source code still comes from
the checkout. Repository updates do not refresh an existing profile's copied
skills automatically; review and copy updates before reusing that profile.

## Set and verify the served context

Replace `YOUR_LOCAL_MODEL:TAG` below with the installed local tag you selected.
Use an unused alias name if `siesta-local:latest` already exists, updating both
copied JSON files to match. This example requests 32768 context tokens and
4096 output tokens; adjust them together for your model and available memory.

```bash
export SIESTA_BASE_MODEL='YOUR_LOCAL_MODEL:TAG'
printf 'FROM %s\nPARAMETER num_ctx 32768\nPARAMETER num_predict 4096\n' "$SIESTA_BASE_MODEL" > .runtime/ollama-local/Modelfile
ollama create siesta-local -f .runtime/ollama-local/Modelfile
curl --fail --silent --show-error http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"siesta-local:latest","prompt":"","keep_alive":"10m","stream":false}'
ollama ps
```

Ollama's OpenAI-compatible endpoint takes context size from the model's
Modelfile; Pi's catalog alone cannot change it. See
[Ollama's context configuration](https://docs.ollama.com/api/openai-compatibility#setting-the-context-size)
and [Modelfile parameters](https://docs.ollama.com/modelfile#parameter).

The alias must appear in `ollama ps` as a loaded local model. Set the copied
Pi catalog's `contextWindow` to the actual `CONTEXT` value, with `maxTokens`
smaller than that window. If it cannot load, reduce the requested context or
choose a model that fits. `/api/ps` also exposes the served context;
[Ollama documents that endpoint](https://docs.ollama.com/api/ps).

The catalog's `apiKey: "ollama"` is a dummy value for the local endpoint,
not a credential. Pi's [custom-model documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)
describes the provider and compatibility fields. This profile declares a
non-thinking model; use a model that works with Siesta's explicit
`--thinking off` and the configured compatibility settings.

## Probe native tools through Pi

Set these variables from the repository root for each new shell. Paths are
derived from the current checkout so subprocesses can find the profile after
changing into a generated project.

```bash
export SIESTA_FACTORY="$PWD/.runtime/ollama-local/factory"
export PI_CODING_AGENT_DIR="$PWD/.runtime/ollama-local/pi"
export PYTHONPATH="$PWD/factory"
export SIESTA_PI_TIMEOUT=1200
mkdir -p .runtime/ollama-local/tool-probe
(
  cd .runtime/ollama-local/tool-probe
  pi -p --provider ollama --model siesta-local:latest --thinking off \
    --no-session --no-extensions --no-skills --no-context-files --mode json \
    'Use write to create probe.py with add(a,b) returning a+b. Use bash to run Python and assert add(2,3)==5. Read probe.py with read. Report only what you actually observed.' \
    > events.jsonl
  python -c 'from probe import add; assert add(2, 3) == 5'
)
```

Inspect `tool-probe/events.jsonl` inside the profile: it must show successful
`tool_execution_end` events for `write`, `bash` and `read`. A final model
sentence or JSON describing tool calls is insufficient. This probe establishes
tool use only; a full project also needs planning, review and verification.
If it fails, fix the model/catalog pairing before using it for a project.

The startup context warning currently reads the default Pi catalog. With
`PI_CODING_AGENT_DIR`, perform the served-context comparison above explicitly.

## Run and resume

With the Python environment active and the profile variables set:

```bash
./factory/bin/siesta.sh --auto 'Build a tiny Python CLI that adds two integers, with pytest tests in every issue'
# Resume using exactly the same idea and profile
./factory/bin/siesta.sh --auto --resume 'Build a tiny Python CLI that adds two integers, with pytest tests in every issue'
```

Python prints each actual role/model/provider assignment at startup. Generated
projects are under `.runtime/ollama-local/factory/projects/`; console output
from the shell launcher is appended to `factory/pipeline.log`. Inspect the
project's checkpoint, verification verdict and KB before treating it as done.

To use different local models per role, create and verify each alias, add each
one to the copied Pi catalog with its served context, and edit the corresponding
role in the copied routing file. No automatic model selection takes place.

Return to the committed default routing in the same shell with:

```bash
unset SIESTA_FACTORY PI_CODING_AGENT_DIR
```
