"""Independent validation and crash-recoverable activation of factory skills."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pipeline import reviews, skill_scenarios
from pipeline.kb import Graph
from pipeline.pi import FACTORY_SKILLS, run_pi

_SKILL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".skill-state-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def _replace_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".skill-candidate-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
    os.replace(temporary, path)


@contextmanager
def _activation_lock(skills_dir: Path):
    state = skills_dir.parent / ".runtime" / "skill-history"
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield state
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _recover(skills_dir: Path, state: Path, graph: Graph) -> None:
    """Finish a committed swap or roll back an interrupted one."""
    for journal in state.glob("*/journal.json"):
        data = json.loads(journal.read_text())
        name = data["skill"]
        if not isinstance(name, str) or not _SKILL_NAME.fullmatch(name):
            raise RuntimeError("Invalid skill activation journal")
        active = skills_dir / name / "SKILL.md"
        node = graph.get(data["proposal_id"])
        payload = json.loads(node["detail"]) if node else {}
        content = active.read_text() if active.is_file() else ""
        if payload.get("status") == "active" and _digest(content) == data["candidate_sha256"]:
            journal.unlink()
            continue
        if data["previous_exists"]:
            _replace_text(active, data["previous_content"])
        elif active.exists():
            active.unlink()
        journal.unlink()


def _review_prompt(payload: dict, scenario_report: dict) -> str:
    return (
        "Independently review this factory skill proposal. The learner is the "
        "author; its claims are untrusted. Compare the full previous and candidate "
        "texts with the recorded evidence. Check that verification gates, tool "
        "boundaries and protocol examples remain sound. Return exactly one JSON "
        "object with version, verdict, summary and findings following the "
        "structured review contract. A pass has no findings.\n\n"
        f"Skill: {payload['skill']}\nReason: {payload['reason']}\n"
        f"Evidence: {json.dumps(payload['evidence'], ensure_ascii=False)}\n"
        f"Scenario validation: {json.dumps(scenario_report, ensure_ascii=False)}\n"
        f"Previous skill:\n{payload['previous_content']}\n"
        f"Candidate skill:\n{payload['proposed_content']}\n"
    )


def _default_reviewer(prompt: str, project: Path) -> str:
    return run_pi("consultant", prompt, "Review factory skill proposal",
                  cwd=project, tools="no", agent="skill-reviewer",
                  context_kind="learning", phase_name="learning")


def _compact_evaluation(report: dict) -> dict:
    """Keep durable results without copying whole model transcripts into the KB."""
    return {stage: {
        "status": result.get("status"),
        "errors": result.get("errors", []),
        "scenarios": [{key: row[key] for key in ("id", "passed", "error") if key in row}
                      for row in result.get("scenarios", [])],
    } for stage, result in report.items() if isinstance(result, dict)}


def review_and_activate(proposal_ids: list[str], graph: Graph, *, project: Path,
                        skills_dir: Path = FACTORY_SKILLS, reviewer=None,
                        evaluator=None) -> dict[str, str]:
    """Review new proposals and activate only those with independent, real evidence.

    A failed call, missing suite or failed scenario leaves the candidate pending.
    Existing project snapshots are untouched, so activation affects future runs.
    """
    project, skills_dir = Path(project), Path(skills_dir)
    evidence = project / ".siesta" / "skill-reviews"
    evidence.mkdir(parents=True, exist_ok=True)
    outcomes = {}
    with _activation_lock(skills_dir) as state:
        _recover(skills_dir, state, graph)
        for proposal_id in proposal_ids:
            node = graph.get(proposal_id)
            if node is None or node["type"] != "skill_proposal":
                raise ValueError(f"Unknown skill proposal: {proposal_id}")
            payload = json.loads(node["detail"])
            if payload.get("status") != "pending":
                outcomes[proposal_id] = payload.get("status", "invalid")
                continue
            name = payload["skill"]
            if (payload.get("scope") != "factory" or not isinstance(name, str)
                    or not _SKILL_NAME.fullmatch(name)):
                raise ValueError("Skill proposal is outside the factory namespace")
            active = skills_dir / name / "SKILL.md"
            if active.is_symlink() or active.parent.is_symlink():
                raise RuntimeError("Factory skill path cannot be a symlink")
            previous = active.read_text() if active.is_file() else ""
            if previous != payload["previous_content"]:
                outcomes[proposal_id] = "conflict"
                payload["activation_error"] = "active skill changed since proposal"
                graph.update_detail(proposal_id, json.dumps(payload, ensure_ascii=False))
                continue
            suite = active.parent / "test_scenarios.yaml"
            if not suite.is_file():
                outcomes[proposal_id] = "pending"
                payload["activation_error"] = "no executable scenario suite for this skill"
                graph.update_detail(proposal_id, json.dumps(payload, ensure_ascii=False))
                continue
            with tempfile.TemporaryDirectory(prefix="candidate-", dir=evidence) as temp:
                candidate_root = Path(temp)
                candidate_dir = candidate_root / name
                shutil.copytree(active.parent, candidate_dir)
                candidate_dir.joinpath("SKILL.md").write_text(payload["proposed_content"])
                report = skill_scenarios.evaluate_suite(
                    candidate_dir / "test_scenarios.yaml", skills_root=candidate_root,
                    real=True, output_dir=candidate_root / "run") if evaluator is None else evaluator(
                        candidate_dir / "test_scenarios.yaml", candidate_root)
                compact = _compact_evaluation(report)
                review_reports = []
                prompt = _review_prompt(payload, compact)
                for _attempt in range(2):
                    try:
                        raw = (reviewer or _default_reviewer)(prompt, project)
                        parsed = reviews.validate_report(raw)
                        review_reports.append(parsed)
                        break
                    except (reviews.ReviewError, ValueError, RuntimeError) as exc:
                        review_reports.append({"error": str(exc)})
                payload["validation"] = {"scenarios": compact, "review": review_reports}
                _save_json(evidence / f"{proposal_id}.json", payload["validation"])
                valid_stages = all(report.get(stage, {}).get("status") == "passed"
                                   for stage in ("format", "simulated", "real"))
                final_review = review_reports[-1]
                if not valid_stages or final_review.get("verdict") != "pass":
                    payload["activation_error"] = (
                        "candidate scenarios did not all pass" if not valid_stages else
                        "independent review did not approve")
                    if final_review.get("verdict") == "findings":
                        payload["status"] = "rejected"
                    graph.update_detail(proposal_id, json.dumps(payload, ensure_ascii=False))
                    outcomes[proposal_id] = payload["status"]
                    continue
            history = state / name
            history.mkdir(parents=True, exist_ok=True)
            if previous:
                _replace_text(history / f"{_digest(previous)}.md", previous)
            journal = history / "journal.json"
            _save_json(journal, {"skill": name, "proposal_id": proposal_id,
                                 "previous_exists": active.is_file(),
                                 "previous_content": previous,
                                 "candidate_sha256": _digest(payload["proposed_content"])})
            try:
                _replace_text(active, payload["proposed_content"])
                payload["status"] = "active"
                payload["activated_at"] = datetime.now(timezone.utc).isoformat()
                payload.pop("activation_error", None)
                graph.update_detail(proposal_id, json.dumps(payload, ensure_ascii=False))
                journal.unlink()
                outcomes[proposal_id] = "active"
            except Exception:
                _recover(skills_dir, state, graph)
                raise
    return outcomes
