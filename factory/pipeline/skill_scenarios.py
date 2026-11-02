"""Validate and run declarative tests for installed factory skills."""
from __future__ import annotations

import re
import os
from pathlib import Path

from pipeline import text
from pipeline.pi import FACTORY_SKILLS

_SUITE_KEYS = {"version", "skill", "agent", "scenarios"}
_SCENARIO_KEYS = {"id", "inputs", "assertions"}
_INPUT_KEYS = {"prompt", "simulated_response", "real_prompt", "execution_log"}
_ASSERTIONS = {
    "contains": {"type", "value"},
    "not_contains": {"type", "value"},
    "marker_outside_fences": {"type", "marker", "expected"},
    "tool_claim_has_execution_evidence": {"type"},
}
_TOOLS = {"read", "write", "edit", "bash", "grep", "find", "ls"}
_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_TOOL_CLAIM = re.compile(
    r"\b(?:i|we)\s+(?:have\s+|did\s+)?(?:read|opened|edited|changed|ran|"
    r"executed|run|tested|searched|wrote|created|updated|inspected|checked|"
    r"verified|committed|saved|installed|deployed|used|called)\b", re.I)


class ScenarioFormatError(ValueError):
    """A scenario file is malformed or requests unsupported behavior."""


def _yaml_load(path: Path) -> object:
    try:
        import yaml
    except ImportError as exc:
        raise ScenarioFormatError(
            "PyYAML is required for development scenario evaluation; install requirements-dev.txt") from exc

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise ScenarioFormatError("YAML mapping keys must be scalar values") from exc
            if duplicate:
                raise ScenarioFormatError(f"duplicate YAML key: {key!r}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return yaml.load(stream, Loader=UniqueKeyLoader)
    except ScenarioFormatError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ScenarioFormatError(f"cannot read YAML: {exc}") from exc


def _exact_keys(value: dict, expected: set[str], where: str) -> None:
    if not all(isinstance(key, str) for key in value):
        raise ScenarioFormatError(f"{where} keys must be strings")
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unsupported " + ", ".join(sorted(unknown)))
        raise ScenarioFormatError(f"{where}: " + "; ".join(details))


def _execution_log(value: object, where: str) -> list[dict]:
    if not isinstance(value, list):
        raise ScenarioFormatError(f"{where}.execution_log must be a list")
    records = []
    for index, record in enumerate(value):
        label = f"{where}.execution_log[{index}]"
        if not isinstance(record, dict):
            raise ScenarioFormatError(f"{label} must be an object")
        _exact_keys(record, {"tool", "action", "result"}, label)
        if not isinstance(record["tool"], str) or record["tool"] not in _TOOLS:
            raise ScenarioFormatError(f"{label}.tool is not a supported tool")
        if any(not isinstance(record[field], str) or not record[field].strip()
               for field in ("action", "result")):
            raise ScenarioFormatError(f"{label} needs non-empty action and result text")
        records.append(dict(record))
    return records


def _validate_assertion(assertion: object, where: str) -> dict:
    if not isinstance(assertion, dict):
        raise ScenarioFormatError(f"{where} must be an object")
    kind = assertion.get("type")
    if not isinstance(kind, str) or kind not in _ASSERTIONS:
        raise ScenarioFormatError(f"{where}: unsupported assertion {kind!r}")
    _exact_keys(assertion, _ASSERTIONS[kind], where)
    if kind in ("contains", "not_contains"):
        if not isinstance(assertion["value"], str) or not assertion["value"]:
            raise ScenarioFormatError(f"{where}.value must be non-empty text")
    elif kind == "marker_outside_fences":
        if not isinstance(assertion["marker"], str) or not assertion["marker"]:
            raise ScenarioFormatError(f"{where}.marker must be non-empty text")
        if type(assertion["expected"]) is not bool:
            raise ScenarioFormatError(f"{where}.expected must be a boolean")
    return dict(assertion)


def load_suite(path: Path, *, skills_root: Path = FACTORY_SKILLS) -> dict:
    """Load a strict version-1 suite belonging to one factory skill."""
    path = Path(path)
    root = Path(skills_root)
    if root.is_symlink() or path.is_symlink():
        raise ScenarioFormatError("skill scenario path cannot traverse symlinks")
    try:
        lexical_path = Path(os.path.abspath(path))
        resolved_root, resolved_path = root.resolve(), path.resolve()
        if lexical_path != resolved_path:
            raise ScenarioFormatError("skill scenario path cannot traverse symlinks")
        relative = resolved_path.relative_to(resolved_root)
    except ScenarioFormatError:
        raise
    except (OSError, ValueError) as exc:
        raise ScenarioFormatError("scenario file must belong to the factory skill tree") from exc
    if (len(relative.parts) != 2 or relative.name != "test_scenarios.yaml"
            or not (resolved_root / relative.parts[0] / "SKILL.md").is_file()
            or (resolved_root / relative.parts[0] / "SKILL.md").is_symlink()):
        raise ScenarioFormatError("scenario file must be test_scenarios.yaml beside a factory SKILL.md")

    document = _yaml_load(resolved_path)
    if not isinstance(document, dict):
        raise ScenarioFormatError("suite root must be a YAML object")
    suite_keys = {"version", "skill", "scenarios"}
    if "agent" in document:
        suite_keys.add("agent")
    _exact_keys(document, suite_keys, "suite")
    if type(document.get("version")) is not int or document["version"] != 1:
        raise ScenarioFormatError("suite.version must be the integer 1")
    skill = document.get("skill")
    if skill != relative.parts[0] or not isinstance(skill, str):
        raise ScenarioFormatError("suite.skill must match its factory skill directory")
    agent = document.get("agent", "consultant")
    if not isinstance(agent, str) or agent not in {"consultant", "worker"}:
        raise ScenarioFormatError("suite.agent must be consultant or worker")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ScenarioFormatError("suite.scenarios must be a non-empty list")

    ids = set()
    validated = []
    for index, raw in enumerate(scenarios):
        where = f"scenarios[{index}]"
        if not isinstance(raw, dict):
            raise ScenarioFormatError(f"{where} must be an object")
        _exact_keys(raw, _SCENARIO_KEYS, where)
        scenario_id = raw.get("id")
        if not isinstance(scenario_id, str) or not _ID.fullmatch(scenario_id):
            raise ScenarioFormatError(f"{where}.id must be a lowercase hyphenated identifier")
        if scenario_id in ids:
            raise ScenarioFormatError(f"duplicate scenario id: {scenario_id}")
        ids.add(scenario_id)
        inputs = raw.get("inputs")
        if not isinstance(inputs, dict):
            raise ScenarioFormatError(f"{where}.inputs must be an object")
        if set(inputs) - _INPUT_KEYS:
            raise ScenarioFormatError(f"{where}.inputs has unsupported fields")
        if not isinstance(inputs.get("prompt"), str) or not inputs["prompt"].strip():
            raise ScenarioFormatError(f"{where}.inputs.prompt must be non-empty text")
        if not isinstance(inputs.get("simulated_response"), str):
            raise ScenarioFormatError(f"{where}.inputs.simulated_response must be text")
        if "real_prompt" in inputs and (not isinstance(inputs["real_prompt"], str)
                                        or not inputs["real_prompt"].strip()):
            raise ScenarioFormatError(f"{where}.inputs.real_prompt must be non-empty text")
        execution_log = _execution_log(inputs.get("execution_log", []), where)
        assertions = raw.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ScenarioFormatError(f"{where}.assertions must be a non-empty list")
        validated.append({
            "id": scenario_id,
            "inputs": {**inputs, "execution_log": execution_log},
            "assertions": [_validate_assertion(assertion, f"{where}.assertions[{n}]")
                           for n, assertion in enumerate(assertions)],
        })
    return {"version": 1, "skill": skill, "agent": agent, "scenarios": validated}


def _run_assertions(assertions: list[dict], response: str,
                    execution_log: list[dict]) -> list[dict]:
    results = []
    fenced_free = text.without_fences(response)
    for assertion in assertions:
        kind = assertion["type"]
        if kind == "contains":
            passed = assertion["value"] in response
            detail = f"response {'contains' if passed else 'does not contain'} the expected text"
        elif kind == "not_contains":
            passed = assertion["value"] not in response
            detail = f"response {'does not contain' if passed else 'contains'} the forbidden text"
        elif kind == "marker_outside_fences":
            found = assertion["marker"] in fenced_free
            passed = found is assertion["expected"]
            detail = (f"marker {assertion['marker']!r} was "
                      f"{'found' if found else 'not found'} outside fenced examples")
        else:
            claims_action = bool(_TOOL_CLAIM.search(fenced_free))
            passed = not claims_action or bool(execution_log)
            detail = ("a claimed tool action has no execution log" if not passed else
                      "tool-action claim is backed by a structured execution log"
                      if claims_action else "no tool action claim was found")
        results.append({"type": kind, "passed": passed, "detail": detail})

    if (_TOOL_CLAIM.search(fenced_free)
            and not any(row["type"] == "tool_claim_has_execution_evidence" for row in results)):
        results.append({"type": "tool_claim_has_execution_evidence",
                        "passed": bool(execution_log),
                        "detail": ("tool-action claim is backed by a structured execution log"
                                   if execution_log else
                                   "a claimed tool action has no execution log")})
    return results


def simulate(suite: dict) -> dict:
    results = []
    for scenario in suite["scenarios"]:
        checks = _run_assertions(scenario["assertions"],
                                 scenario["inputs"]["simulated_response"],
                                 scenario["inputs"]["execution_log"])
        results.append({"id": scenario["id"], "passed": all(row["passed"] for row in checks),
                        "assertions": checks})
    return {"status": "passed" if all(row["passed"] for row in results) else "failed",
            "scenarios": results}


def _default_invoker(*, suite: dict, scenario: dict, output_dir: Path,
                     skill_dir: Path):
    from pipeline.pi import run_pi
    agent = suite["agent"]
    role = "worker" if agent == "worker" else "consultant"
    context = "issue" if role == "worker" else "learning"
    tools = None if role == "worker" else "no"
    prompt = scenario["inputs"].get("real_prompt", scenario["inputs"]["prompt"])
    response = run_pi(
        role, prompt, f"Evaluate factory skill {suite['skill']} scenario {scenario['id']}",
        skills=(skill_dir,), cwd=output_dir, tools=tools, agent=agent,
        context_kind=context,
        phase_name="implementation" if role == "worker" else "learning")
    # Pi's text interface does not expose structured tool events to this runner.
    return response, []


def evaluate_real(suite: dict, *, output_dir: Path, skills_root: Path,
                  invoker=None) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    skill_dir = Path(skills_root) / suite["skill"]
    invoke = invoker or _default_invoker
    results = []
    for scenario in suite["scenarios"]:
        try:
            result = invoke(suite=suite, scenario=scenario,
                            output_dir=output_dir, skill_dir=skill_dir)
            if isinstance(result, tuple) and len(result) == 2:
                response, execution_log = result
            elif isinstance(result, dict):
                response, execution_log = result.get("response"), result.get("execution_log")
            else:
                response, execution_log = result, []
            if not isinstance(response, str):
                raise ValueError("scenario invoker returned no text response")
            if not isinstance(execution_log, list):
                raise ValueError("scenario invoker returned no execution log list")
            execution_log = _execution_log(execution_log,
                                           f"scenario {scenario['id']} runtime")
            checks = _run_assertions(scenario["assertions"], response, execution_log)
            results.append({"id": scenario["id"], "passed": all(row["passed"] for row in checks),
                            "response": response, "assertions": checks,
                            "execution_log": execution_log})
        except Exception as exc:
            results.append({"id": scenario["id"], "passed": False, "error": str(exc),
                            "assertions": []})
    return {"status": "passed" if all(row["passed"] for row in results) else "failed",
            "scenarios": results}


def evaluate_suite(path: Path, *, real: bool = False, output_dir: Path | None = None,
                   skills_root: Path = FACTORY_SKILLS, invoker=None) -> dict:
    """Return separate format, simulated and optional live evaluation results."""
    report = {"format": {"status": "pending", "errors": []},
              "simulated": {"status": "skipped", "scenarios": []},
              "real": {"status": "not_run", "scenarios": []}}
    try:
        suite = load_suite(path, skills_root=skills_root)
    except ScenarioFormatError as exc:
        report["format"] = {"status": "failed", "errors": [str(exc)]}
        if real:
            report["real"]["status"] = "skipped"
        return report
    report["format"] = {"status": "passed", "errors": [], "skill": suite["skill"],
                        "scenario_ids": [scenario["id"] for scenario in suite["scenarios"]]}
    report["simulated"] = simulate(suite)
    if real:
        if output_dir is None:
            report["real"] = {"status": "failed", "scenarios": [],
                              "error": "output_dir is required for real evaluation"}
        else:
            report["real"] = evaluate_real(suite, output_dir=output_dir,
                                           skills_root=skills_root, invoker=invoker)
    return report
