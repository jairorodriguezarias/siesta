# Retro desktop

## Objective

Give the local Siesta operator a 1990s-style browser desktop for launching
projects, answering the interview, inspecting progress and evidence, and
playing Snake during model work. Keep the existing Python CLI authoritative.

## Capability map and order

| Module | Responsibility | Depends on |
| --- | --- | --- |
| snake | Keyboard/touch game, pause, restart, local high score | — |
| desktop | Responsive windows, taskbar, project and activity views | snake |
| local-runner | Start the existing CLI, transport interview replies and status | — |
| project-browser | List projects and read selected evidence | local-runner |

Build order: snake and desktop → local-runner → project-browser → browser checks.

## Stack and structure

Use Python standard-library HTTP and subprocess support, plus local HTML,
CSS and JavaScript modules in `factory/pipeline/web/`. No frontend build,
external fonts, CDN, account, hosted service or runtime dependency is needed.
`pipeline.web` serves the desktop on loopback. A small optional status writer
provides explicit phase/input events; normal CLI behavior stays unchanged.

Run: `PYTHONPATH=factory python3 -m pipeline.web --port 8765`.
Python checks: `cd factory && python -B -m unittest discover -s tests -v`.
Game checks: `node --test factory/tests/test_snake.mjs`.
Use the project's existing Python environment with pytest for the full suite.

## Boundaries and decisions

- Local, single operator; serialize runs because the shared KB has one writer.
- Launch the same interpreter and pipeline with an argument list, never a shell.
- Restrict HTTP to loopback with Host/Origin checks and a per-server request token.
- Serve only known assets and selected, bounded project documents. Render model
  output as text; never execute returned markup or expose arbitrary files.
- Browser refresh must reconnect without restarting the run. Closing the browser
  leaves the server running; stopping the server terminates its process group.
- Keep docs in English; use English UI labels consistent with pipeline output.
- Always test game rules, process outcomes, input handoff and request boundaries.
- Ask before exposing this service beyond the local machine or adding accounts.
- Never infer successful completion from process exit zero alone, overwrite
  spec/plan through the UI, or send project contents to third-party services.

Use small Python functions and explicit JSON objects, e.g.
`return {"status": "waiting", "phase": "0", "input_id": input_id}`.
Keep game rules pure and separate from DOM/canvas drawing.

## Acceptance criteria

- R1: Desktop has beveled windows, a taskbar and restrained retro colors; it is
  usable at desktop and narrow mobile widths with keyboard-visible focus.
- R2: Snake supports arrows/WASD, touch controls, start/pause/restart, food,
  growth, wall/self collision and a local high score. It pauses when hidden
  or unfocused, and never takes keys from forms or another window.
- R3: Launching an idea starts the existing pipeline once; concurrent starts
  are rejected. Interview replies go to that process only while it awaits one.
- R4: Phase, recent console output, elapsed time and terminal result update
  without reload. Refresh preserves the live run and its input request.
- R5: A persistent in-app notice appears on input requests and completion,
  including while playing. No forced browser-notification permission prompt.
- R6: Existing projects can be inspected and resumed with their recorded idea;
  selected specs, plans and requirement evidence are viewable as plain text.
- R7: Passing means exit zero AND a complete checkpoint AND VERIFY_PASSED;
  failed, stopped and incomplete processes stay visibly distinct from success.
- R8: Tests cover meaningful rules and failure paths. Browser verification
  exercises the real HTTP adapter with a controlled child process and checks
  desktop/mobile layouts and console errors. Live paid-model runs are separate.

## Verification strategy

Use unittest with temporary factories and real subprocesses for the service,
Node's built-in test runner for game rules, and a browser smoke test for form
input, keyboard isolation, refresh/reconnection, notices and screenshots.
Run the existing Python regression suite before completion. Record actual
checks and limitations in the desktop guide.
