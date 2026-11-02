"""Migrate legacy project evidence without changing its committed issue ledger."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pipeline import issue_reviews, repository, reviews

MIGRATION_FILE = ".siesta/migration.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(path: Path, value: dict) -> None:
    if path.is_symlink() or path.with_suffix(".tmp").is_symlink():
        raise RuntimeError("migration evidence path cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _approved_issue_review(project: Path, number: int) -> bool:
    folder = project / ".siesta" / "reviews"
    if not folder.is_dir() or folder.is_symlink():
        return False
    issue = repository.read_plan(project)[number]
    level = repository.issue_review_level(issue)
    reviewers = ("integration-reviewer", "quality-reviewer") if level == "extended" \
        else ("integration-reviewer",)
    base = _issue_base(project, number)
    configuration = issue_reviews._issue_review_configuration(project, number, issue, reviewers)
    identity = hashlib.sha256(
        f"{number}:{repository.issue_digest(issue)}:{base}:{configuration}".encode()
    ).hexdigest()[:60]
    path = folder / f"issue-{number}-{identity}.json"
    if not path.is_file() or path.is_symlink():
        return False
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(record, dict):
        return False
    rounds = record.get("rounds")
    last_round = rounds[-1] if isinstance(rounds, list) and rounds else None
    return (record.get("status") == "approved"
            and isinstance(last_round, dict)
            and last_round.get("status") == "clean"
            and record.get("approved_version") == last_round.get("version")
            and record.get("policy_name") == reviews.project_policy(project))


def prepare(project: Path, *, was_existing: bool, was_complete: bool,
            legacy_configuration: bool) -> dict | None:
    """Pin migration facts and identify completed issues lacking review evidence."""
    project = Path(project)
    path = project / MIGRATION_FILE
    if path.exists():
        if path.is_symlink():
            raise RuntimeError("migration evidence path cannot be a symlink")
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or value.get("version") != 1:
            raise RuntimeError("migration evidence is invalid")
        return value
    if not was_existing:
        return None
    completed = sorted(repository.completed_issues(project))
    missing = [] if was_complete else [number for number in completed
                                       if not _approved_issue_review(project, number)]
    if not legacy_configuration and not missing:
        return None
    evidence = project / ".siesta"
    value = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "finished" if was_complete else "pending" if missing else "complete",
        "completed_issues": completed,
        "pending_issue_reviews": missing,
        "skill_versions_sha256": _sha(evidence / "skill-versions.json"),
        "model_selection_sha256": _sha(evidence / "model-selection.json"),
        "review_policy_sha256": _sha(evidence / "review-policy.json"),
        "legacy_configuration": legacy_configuration,
        "revalidation": [],
    }
    _save(path, value)
    return value


def _issue_base(project: Path, number: int) -> str:
    """Find the commit before the first committed completion claim."""
    output = repository.checked_git(
        project, "log", "--reverse", "--format=%H", "-S",
        f"Issue #{number} completed", "--", "kb/graph.json").decode().splitlines()
    if not output:
        raise RuntimeError(f"Cannot locate the committed base of issue #{number}")
    commit = output[0].strip()
    parents = repository.checked_git(project, "rev-list", "--parents", "-n", "1", commit).decode().split()
    if len(parents) < 2:
        empty = subprocess.run(["git", "-C", str(project), "mktree"], input=b"",
                               capture_output=True, check=True)
        return empty.stdout.decode().strip()
    return parents[1]


def revalidate_completed(project: Path, migration: dict, *,
                         run_regression, run_pi, gather_fn,
                         repair_skills=(), worker_thinking="off") -> dict:
    """Independently review old completed issues before a later issue can run."""
    path = Path(project) / MIGRATION_FILE
    if migration.get("status") != "pending":
        return migration
    issues = repository.read_plan(project)
    for number in list(migration["pending_issue_reviews"]):
        if number not in repository.completed_issues(project):
            raise RuntimeError(f"Migration ledger changed for issue #{number}")
        if run_regression(project, number) != "passed":
            raise RuntimeError(f"Legacy issue #{number} failed its regression suite")
        before = repository.completed_issues(project)
        approved = issue_reviews.review_issue(
            project, number, issues[number], _issue_base(project, number),
            run_pi=run_pi, run_regression=run_regression,
            gather_fn=gather_fn, repair_skills=repair_skills,
            worker_thinking=worker_thinking)
        if not approved:
            raise RuntimeError(f"Legacy issue #{number} failed independent revalidation")
        if repository.completed_issues(project) != before:
            raise RuntimeError("Migration changed the committed issue ledger")
        if repository.checked_git(project, "status", "--porcelain").strip():
            repository.require_committed_ledger(project)
            repository.commit(project, f"Review legacy issue #{number} repair")
        migration["pending_issue_reviews"].remove(number)
        migration["revalidation"].append({
            "issue": number, "approved_at": datetime.now(timezone.utc).isoformat(),
            "product_sha256": repository.fingerprint(project),
        })
        _save(path, migration)
    migration["status"] = "complete"
    _save(path, migration)
    return migration
