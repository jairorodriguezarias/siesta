"""Explicit agent identities and Python-enforced invocation permissions."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Agent:
    id: str
    model_role: str
    definition_path: Path
    allowed_tools: tuple[str, ...]
    allowed_contexts: tuple[str, ...]
    response_format: str


FACTORY = Path(os.environ["SIESTA_FACTORY"]).resolve() if os.environ.get("SIESTA_FACTORY") \
    else Path(__file__).resolve().parent.parent
AGENT_DIR = FACTORY / "agents"
_TOOL_NAMES = {"read", "write", "edit", "bash", "grep", "find", "ls"}

AGENTS = {
    "planner": Agent(
        id="planner", model_role="planner",
        definition_path=AGENT_DIR / "planner.md", allowed_tools=(),
        allowed_contexts=("intent", "interview", "specification", "plan", "pipeline"),
        response_format="Follow the phase's explicit output contract.",
    ),
    "worker": Agent(
        id="worker", model_role="worker",
        definition_path=AGENT_DIR / "worker.md",
        allowed_tools=("read", "write", "edit", "bash", "grep", "find", "ls"),
        allowed_contexts=("issue", "project", "source", "tests", "pipeline"),
        response_format="Perform authorized work and report concrete evidence.",
    ),
    "consultant": Agent(
        id="consultant", model_role="consultant",
        definition_path=AGENT_DIR / "consultant.md", allowed_tools=(),
        allowed_contexts=("consultation", "review", "learning", "design", "pipeline"),
        response_format="Follow the caller's explicit advice or review format.",
    ),
    "integration-reviewer": Agent(
        id="integration-reviewer", model_role="consultant",
        definition_path=AGENT_DIR / "integration-reviewer.md", allowed_tools=(),
        allowed_contexts=("review",),
        response_format="Return one structured JSON review report.",
    ),
    "quality-reviewer": Agent(
        id="quality-reviewer", model_role="consultant",
        definition_path=AGENT_DIR / "quality-reviewer.md", allowed_tools=(),
        allowed_contexts=("review",),
        response_format="Return one structured JSON review report.",
    ),
}


def get_agent(agent_id: str, *, model_role: str, context_kind: str = "pipeline") -> Agent:
    """Return a known agent after checking its role and admitted context type."""
    try:
        agent = AGENTS[agent_id]
    except KeyError as exc:
        raise ValueError(f"unknown agent: {agent_id}") from exc
    if agent.model_role != model_role:
        raise ValueError(f"agent {agent_id} uses model role {agent.model_role}, "
                         f"not {model_role}")
    if context_kind not in agent.allowed_contexts:
        raise ValueError(f"context {context_kind!r} is not allowed for agent {agent_id}")
    if (not agent.response_format.strip()
            or len(set(agent.allowed_tools)) != len(agent.allowed_tools)
            or any(tool not in _TOOL_NAMES for tool in agent.allowed_tools)):
        raise RuntimeError(f"agent {agent_id} has invalid registry metadata")
    return agent


def load_definition(agent: Agent) -> str:
    """Load and validate the required Markdown definition for each invocation."""
    try:
        content = agent.definition_path.read_text().strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"agent {agent.id} definition is missing or unreadable: "
            f"{agent.definition_path}") from exc
    required_sections = ("## Role", "## Context allowed", "## Response format",
                        "## Tool policy")
    lines = content.splitlines()
    sections_valid = True
    for section in required_sections:
        try:
            start = lines.index(section) + 1
        except ValueError:
            sections_valid = False
            break
        end = next((i for i in range(start, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        if not any(line.strip() for line in lines[start:end]):
            sections_valid = False
            break
    if (not content.startswith(f"# Agent: {agent.id}\n") or not sections_valid):
        raise RuntimeError(f"agent {agent.id} definition is invalid: "
                           f"{agent.definition_path}")
    return content


def permitted_tools(agent: Agent, requested: str | None) -> tuple[str, ...]:
    """Resolve a caller request as a subset of the agent's trusted allowlist."""
    if requested == "no":
        return ()
    if requested is not None and not requested.strip():
        raise ValueError("tool request must be 'no' or a non-empty tool list")
    tools = agent.allowed_tools if requested is None else tuple(
        part.strip() for part in requested.split(",") if part.strip())
    if (len(set(tools)) != len(tools)
            or any(tool not in agent.allowed_tools for tool in tools)):
        raise ValueError(f"requested tool is not allowed for agent {agent.id}: {requested}")
    return tools
