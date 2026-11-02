"""Validated, project-local model routes with phase and agent precedence."""
import json
from pathlib import Path

from pipeline.agents import AGENTS

PHASES = (
    "interview", "intent_review", "specification", "planning", "design_review",
    "design_repair",
    "implementation", "issue_review", "review", "verification", "completion", "learning",
    "iteration_specification", "iteration_planning",
)
ROLES = ("planner", "worker", "consultant")
SELECTION_FILE = ".siesta/model-selection.json"


def _route(value, label: str) -> dict:
    if (not isinstance(value, dict) or set(value) != {"model", "provider"}
            or any(not isinstance(value[key], str) or not value[key].strip()
                   or value[key] != value[key].strip()
                   for key in ("model", "provider"))):
        raise ValueError(f"invalid model route for {label}: expected model and provider strings")
    return {"model": value["model"], "provider": value["provider"]}


def _role_defaults(value) -> dict:
    if not isinstance(value, dict) or set(value) != set(ROLES):
        raise ValueError("model selection requires defaults for planner, worker, and consultant")
    return {role: _route(value[role], f"role {role}") for role in ROLES}


def normalize_selection(value, *, role_defaults: dict | None = None) -> dict:
    """Validate user or saved selections and return a detached canonical value."""
    if not isinstance(value, dict):
        raise ValueError("model selection must be a JSON object")
    allowed_keys = {"version", "role_defaults", "phases", "agents"}
    if set(value) - allowed_keys:
        raise ValueError("model selection has unknown fields")
    version = value.get("version", 1)
    if type(version) is not int or version != 1:
        raise ValueError(f"unsupported model selection version: {version}")
    defaults = _role_defaults(value.get("role_defaults", role_defaults))
    phase_routes = value.get("phases", {})
    agent_routes = value.get("agents", {})
    if not isinstance(phase_routes, dict) or not isinstance(agent_routes, dict):
        raise ValueError("phases and agents must be JSON objects")
    normalized_phases = {}
    for phase, route in phase_routes.items():
        if phase not in PHASES:
            raise ValueError(f"unknown phase in model selection: {phase}")
        normalized_phases[phase] = _route(route, f"phase {phase}")
    normalized_agents = {}
    for phase, routes in agent_routes.items():
        if phase not in PHASES:
            raise ValueError(f"unknown phase in model selection: {phase}")
        if not isinstance(routes, dict):
            raise ValueError(f"agent routes for phase {phase} must be a JSON object")
        normalized_agents[phase] = {}
        for agent_id, route in routes.items():
            if agent_id not in AGENTS:
                raise ValueError(f"unknown agent in model selection: {agent_id}")
            normalized_agents[phase][agent_id] = _route(
                route, f"agent {agent_id} in phase {phase}")
    return {"version": 1, "role_defaults": defaults,
            "phases": normalized_phases, "agents": normalized_agents}


def from_overrides(value, *, role_defaults: dict) -> dict:
    """Create a project selection without allowing per-run edits to role defaults."""
    if not isinstance(value, dict):
        raise ValueError("model selection must be a JSON object")
    if "role_defaults" in value:
        raise ValueError("role defaults come from the Siesta model configuration")
    return normalize_selection(value, role_defaults=role_defaults)


def resolve_route(selection: dict, phase: str, agent_id: str, model_role: str) -> dict:
    """Apply agent-in-phase, phase, then snapshotted role-default precedence."""
    if phase not in PHASES:
        raise ValueError(f"unknown model selection phase: {phase}")
    try:
        agent = AGENTS[agent_id]
    except KeyError as exc:
        raise ValueError(f"unknown agent: {agent_id}") from exc
    if agent.model_role != model_role:
        raise ValueError(f"agent {agent_id} uses model role {agent.model_role}, not {model_role}")
    normalized = normalize_selection(selection)
    route = normalized["agents"].get(phase, {}).get(agent_id)
    route = route or normalized["phases"].get(phase)
    route = route or normalized["role_defaults"][model_role]
    return dict(route)


def project_path(project: Path) -> Path:
    return project / SELECTION_FILE


def load_project(project: Path) -> dict | None:
    """Load the pinned project selection; malformed state fails explicitly."""
    path = project_path(project)
    if (project / ".siesta").is_symlink() or path.is_symlink():
        raise ValueError(f"saved model selection cannot be a symlink: {path}")
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read saved model selection: {path}") from exc
    return normalize_selection(raw)


def save_project(project: Path, selection: dict) -> Path:
    """Atomically persist a normalized selection in the project's evidence."""
    normalized = normalize_selection(selection)
    path = project_path(project)
    if (path.parent.is_symlink() or path.is_symlink()
            or path.with_suffix(".tmp").is_symlink()):
        raise ValueError(f"model selection path cannot be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return path
