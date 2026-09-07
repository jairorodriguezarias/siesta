"""Model access and logging — every model call goes through run_pi().

The pipeline shells out to the `pi` CLI (installed on PATH), exactly as the
bash version did. Nothing here knows about phases; capture and artifact
writing are the only concerns.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PI_BIN = "pi"

# #10: a hung pi/Ollama call must never freeze the pipeline — stop.md only
# works between issues. Override with SIESTA_PI_TIMEOUT (seconds).
PI_TIMEOUT = int(os.environ.get("SIESTA_PI_TIMEOUT", "1200"))

# SIESTA_FACTORY redirects projects/, kb/ and skills/ (used by tests).
FACTORY = Path(os.environ["SIESTA_FACTORY"]) if os.environ.get("SIESTA_FACTORY") \
    else Path(__file__).resolve().parent.parent
SKILLS = FACTORY.parent / ".agents" / "skills"       # addyosmani skills, repo root
FACTORY_SKILLS = FACTORY / "skills"                  # factory skills, self-improving
CONFIG = FACTORY / "config" / "models.json"
GLOBAL_KB = FACTORY / "kb" / "global-graph.json"

_config = json.loads(CONFIG.read_text())
ROLE = {r: {"model": _config[r]["model"], "provider": _config[r]["provider"]}
        for r in ("planner", "worker", "consultant")}

# #24: pi without an explicit --thinking sends a level Ollama rejects for
# non-thinking models (qwen2.5-coder 400s: "does not support thinking"). The
# flag is therefore load-bearing. But a *non-default* level on a model that
# does not support thinking also 400s (deep-diagnosis "high" on qwen) — so
# only forward --thinking when the routed model is a known thinking model;
# for others pin "off", which every provider accepts.
THINKING_MODELS = ("glm",)

# Round-8: pi's catalog (~/.pi/agent/models.json) declared gemma4 with a
# 131072 window while Ollama served 8192 — pi never compacted, worker prompts
# overflowed, --context-shift silently cut the head (skills + closing
# directive), and the model ended its turn on a tool call with empty stdout
# (issues #3/#4 "degenerate"). The catalog must state the TRUE served window.
PI_CATALOG = Path.home() / ".pi" / "agent" / "models.json"


def _safe_thinking(model: str, thinking: str) -> str:
    lowered = model.lower()
    if any(family in lowered for family in THINKING_MODELS):
        return thinking
    return "off"


def _served_context(model: str) -> int | None:
    """Ollama's actually-served context for a loaded model, None if unknown.

    `/api/ps` (the JSON behind `ollama ps`'s CONTEXT column) is the truth
    the catalog must match; a None probe (Ollama absent, unreadable, model
    idle) must never warn. `ollama ps` has no --format flag (0.33.3), and
    its table output is locale-unstable — parse the API, not the table.
    """
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps",
                                    timeout=10) as resp:
            entries = json.loads(resp.read().decode() or "")
            if isinstance(entries, dict):        # {"models": [...]} shape
                entries = entries.get("models", [])
            for entry in entries:
                if entry.get("name") == model:
                    length = entry.get("context_length")
                    if isinstance(length, int) and length > 0:
                        return length
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return None


def _declared_context(model: str) -> int | None:
    """pi's catalog window for the model, None when not registered."""
    try:
        catalog = json.loads(PI_CATALOG.read_text())
        for entry in (catalog.get("providers", {}).get("ollama", {})
                      .get("models", [])):
            if entry.get("id") == model:
                window = entry.get("contextWindow")
                if isinstance(window, int) and window > 0:
                    return window
    except (OSError, ValueError):
        return None
    return None


def warn_if_context_mismatch(model: str, declared: int | None) -> bool:
    """Advisory guard: warn when the served window is smaller than declared.

    pi compacts to the catalog window, so a bigger declared window silently
    truncates real context (pomodoro run: 131072 declared vs 8192 served).
    """
    served = _served_context(model)
    if served is None or declared is None or served >= declared:
        return False
    warn(f"pi catalog says {model} has {declared} context but Ollama serves "
         f"{served} — pi will not compact; long prompts get silently "
         f"truncated (worker turns can lose the closing directive)")
    return True

# ANSI colors for the log helpers
_CYAN, _GREEN, _YELLOW, _RED, _NC = ("\033[0;36m", "\033[0;32m", "\033[0;33m",
                                     "\033[0;31m", "\033[0m")


def log(msg: str) -> None:
    print(f"{_CYAN}[pipeline]{_NC} {msg}", file=sys.stderr)


def ok(msg: str) -> None:
    print(f"{_GREEN}[ok]{_NC} {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"{_YELLOW}[warn]{_NC} {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"{_RED}[error]{_NC} {msg}", file=sys.stderr)


def phase(n: int | str, title: str) -> None:
    print(f"{_CYAN}══━─ Phase {n}: {title} ─━══{_NC}", file=sys.stderr)


def _child_env() -> dict:
    """Env for pi children: models must be able to run the KB shim
    (`python3 -m pipeline.kb ...`) from the project cwd, so the factory
    dir has to stay on PYTHONPATH regardless of how we were launched."""
    path = os.environ.get("PYTHONPATH", "")
    return {**os.environ, "PYTHONPATH": f"{FACTORY}{os.pathsep}{path}".rstrip(os.pathsep)}


def build_args(role: str, body: str, user: str, *, skills=(), thinking: str = "off",
               interactive: bool = False, tools: str | None = None) -> list[str]:
    """One canonical pi argument list — order matters only for readability.

    tools="no" adds --no-tools (text-protocol phases: the model must answer
    with protocol markers, not tool calls); a name list adds an allowlist.

    body + user go in ONE positional prompt (data first, directive last):
    pi 0.84.3 stopped delivering --append-system-prompt content to the model
    (verified for both glm-5.2:cloud and qwen2.5-coder — #23). Keep the
    "model obeys the last turn" order from runs #3/#4.
    """
    args = [PI_BIN]
    if not interactive:
        args.append("-p")
    args += ["--model", ROLE[role]["model"],
             "--provider", ROLE[role]["provider"],
             "--thinking", _safe_thinking(ROLE[role]["model"], thinking)]
    if tools == "no":
        args += ["--no-tools"]
    elif tools:
        args += ["--tools", tools]
    for s in skills:
        args += ["--skill", f"{Path(s).as_posix().rstrip('/')}/"]
    args += [f"{body}\n\n{user}"]
    return args


def run_pi(role: str, body: str, user: str, *, skills=(), thinking: str = "off",
           interactive: bool = False, artifact: Path | None = None,
           cwd: Path | None = None, tools: str | None = None) -> str:
    """Run pi for a role; return the output text, optionally saving an artifact.

    cwd is the project dir — models write spec.md/issues.md/source relative
    to it (bash did `cd "$PROJECT_DIR"` once for the whole run).
    """
    args = build_args(role, body, user, skills=skills, thinking=thinking,
                      interactive=interactive, tools=tools)
    where = str(cwd) if cwd else None
    env = _child_env()
    if interactive:
        # Phase 0 conversation: stream to the human while recording (tee).
        # #35: the interactive path gets the same #10 timeout — a hung
        # pi/Ollama call must not freeze phase 0 forever. The human can
        # still leave naturally (EOF ends the stream; wait returns fast).
        chunks: list[str] = []
        with subprocess.Popen(args, stdout=subprocess.PIPE, text=True,
                              cwd=where, env=env) as p:
            for line in p.stdout:
                print(line, end="")
                chunks.append(line)
            try:
                p.wait(timeout=PI_TIMEOUT)
            except subprocess.TimeoutExpired:
                p.kill()
                err(f"interactive pi call timed out after {PI_TIMEOUT}s "
                    f"— treating as no answer")
                text_out = "".join(chunks)
                _maybe_write(artifact, text_out)
                return text_out
        text_out = "".join(chunks)
        _maybe_write(artifact, text_out)
        return text_out
    try:
        result = subprocess.run(args, capture_output=True, text=True, cwd=where,
                                env=env, timeout=PI_TIMEOUT)
        # Hardening (round-7): stdout is the model's answer; stderr is
        # provider noise (pi warnings polluted the pomodoro run's parsed
        # artifacts — and could falsify markers). Parse stdout only; keep
        # stderr as evidence below a PROVIDER_LOG: separator.
        text_out = result.stdout or ""
        stderr_out = (result.stderr or "").strip()
        if stderr_out:
            warn("pi stderr: " + " / ".join(stderr_out.splitlines()[:3]))
    except subprocess.TimeoutExpired:
        # #10: a timed-out call is "no answer" — the empty return flows into
        # the degenerate-output guards, which treat it as a failed attempt.
        err(f"pi call timed out after {PI_TIMEOUT}s — treating as no answer")
        text_out, stderr_out = "", ""
    _maybe_write(artifact, text_out, stderr_out)
    return text_out


def _maybe_write(artifact: Path | None, text_out: str, stderr_out: str = "") -> None:
    if artifact is None:
        return
    content = text_out
    if stderr_out:
        content += f"\nPROVIDER_LOG: {stderr_out}\n"
    artifact.write_text(content)