"""Model access and logging — every model call goes through run_pi().

The pipeline shells out to the `pi` CLI (installed on PATH), exactly as the
bash version did. Nothing here knows about phases; capture and artifact
writing are the only concerns.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PI_BIN = "pi"

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
    """
    args = [PI_BIN]
    if not interactive:
        args.append("-p")
    args += ["--model", ROLE[role]["model"],
             "--provider", ROLE[role]["provider"],
             "--thinking", thinking]
    if tools == "no":
        args += ["--no-tools"]
    elif tools:
        args += ["--tools", tools]
    for s in skills:
        args += ["--skill", f"{Path(s).as_posix().rstrip('/')}/"]
    args += ["--append-system-prompt", body, user]
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
        chunks: list[str] = []
        with subprocess.Popen(args, stdout=subprocess.PIPE, text=True,
                              cwd=where, env=env) as p:
            for line in p.stdout:
                print(line, end="")
                chunks.append(line)
            p.wait()
        text_out = "".join(chunks)
        _maybe_write(artifact, text_out)
        return text_out
    result = subprocess.run(args, capture_output=True, text=True, cwd=where,
                            env=env)
    # Bash piped everything through 2>&1; models sometimes narrate on stderr.
    text_out = (result.stdout or "") + (result.stderr or "")
    _maybe_write(artifact, text_out)
    return text_out


def _maybe_write(artifact: Path | None, text_out: str) -> None:
    if artifact is not None:
        artifact.write_text(text_out)