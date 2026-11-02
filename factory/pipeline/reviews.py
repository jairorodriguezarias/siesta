"""Persistent, bounded review sessions shared by pipeline review phases."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path


class ReviewError(RuntimeError):
    """A review transition or report violated the review contract."""


POLICIES = {
    "normal": {"max_rounds": 3, "max_repairs": 2, "clean_rounds": 1},
    "deep": {"max_rounds": 5, "max_repairs": 2, "clean_rounds": 2},
}
MAX_REVIEW_ATTEMPTS = 2
MAX_STORED_RESPONSE = 256_000
REPORT_FIELDS = {"version", "verdict", "summary", "findings"}
FINDING_FIELDS = {"id", "severity", "target", "evidence", "requested_fix"}
SEVERITIES = {"critical", "major", "minor", "info"}
VERDICTS = {"pass", "findings", "insufficient_evidence"}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReviewError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value, label: str, *, limit: int = 12000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ReviewError(f"{label} must be a nonempty string of at most {limit} characters")
    return value.strip()


def _preserve_response(attempt: dict, response: str | None) -> None:
    if not isinstance(response, str):
        return
    if len(response) <= MAX_STORED_RESPONSE:
        attempt["response"] = response
        return
    encoded = response.encode("utf-8", errors="surrogatepass")
    attempt["response_preview"] = response[:4000]
    attempt["response_chars"] = len(response)
    attempt["response_sha256"] = hashlib.sha256(encoded).hexdigest()


def _validate_context(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"included", "omitted"}:
        raise ReviewError("context manifest must contain included and omitted paths")
    result = {}
    for key in ("included", "omitted"):
        paths = value[key]
        if (not isinstance(paths, list)
                or any(not isinstance(path, str) or not path.strip() or "\x00" in path
                       for path in paths)
                or len(paths) > 1000):
            raise ReviewError(f"context manifest {key} must contain unique nonempty paths")
        normalized = [path.strip() for path in paths]
        if len(normalized) != len(set(normalized)):
            raise ReviewError(f"context manifest {key} must contain unique nonempty paths")
        result[key] = normalized
    if not result["included"]:
        raise ReviewError("review context has no included evidence")
    if set(result["included"]) & set(result["omitted"]):
        raise ReviewError("context paths cannot be both included and omitted")
    return result


def validate_report(value) -> dict:
    """Validate the reviewer's strict JSON report and return a detached value."""
    if isinstance(value, str):
        if len(value) > 256_000:
            raise ReviewError("review report exceeds 256000 characters")
        try:
            value = json.loads(value, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ReviewError) as exc:
            raise ReviewError("review report is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != REPORT_FIELDS:
        raise ReviewError("review report must contain exactly version, verdict, summary, and findings")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ReviewError("unsupported review report version")
    verdict = value["verdict"]
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise ReviewError("unknown review verdict")
    summary = _text(value["summary"], "review summary")
    findings = value["findings"]
    if not isinstance(findings, list):
        raise ReviewError("review findings must be a list")
    normalized = []
    identifiers = set()
    for item in findings:
        if not isinstance(item, dict) or set(item) != FINDING_FIELDS:
            raise ReviewError("each finding must contain exactly id, severity, target, evidence, and requested_fix")
        identifier = _text(item["id"], "finding id", limit=80)
        if identifier in identifiers:
            raise ReviewError(f"duplicate finding id: {identifier}")
        identifiers.add(identifier)
        severity = item["severity"]
        if not isinstance(severity, str) or severity not in SEVERITIES:
            raise ReviewError(f"unknown finding severity: {severity}")
        normalized.append({
            "id": identifier,
            "severity": severity,
            "target": _text(item["target"], "finding requirement or location"),
            "evidence": _text(item["evidence"], "finding evidence"),
            "requested_fix": _text(item["requested_fix"], "requested correction"),
        })
    if verdict == "pass" and normalized:
        raise ReviewError("a passing report cannot contain findings")
    if verdict == "findings" and not normalized:
        raise ReviewError("a findings report must contain at least one finding")
    if verdict == "insufficient_evidence" and normalized:
        raise ReviewError("insufficient evidence must be reported without findings")
    return {"version": 1, "verdict": verdict, "summary": summary,
            "findings": normalized}


class ReviewSession:
    """One durable review ledger, stored under the project's ignored evidence."""

    def __init__(self, project: Path, review_id: str, *, policy: str = "normal",
                 author: str = "worker"):
        if not isinstance(review_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", review_id):
            raise ReviewError("invalid review identifier")
        if not isinstance(policy, str) or policy not in POLICIES:
            raise ReviewError(f"unknown review policy: {policy}")
        author = _text(author, "review author", limit=80)
        self.project = Path(project)
        self.path = self.project / ".siesta" / "reviews" / f"{review_id}.json"
        self._guard_path()
        if self.path.exists():
            self.state = self._read()
            if self.state["review_id"] != review_id:
                raise ReviewError("saved review identifier does not match its file")
            if self.state["policy_name"] != policy or self.state["author"] != author:
                raise ReviewError("review policy and author are fixed when a review starts")
        else:
            self.state = {
                "version": 1,
                "review_id": review_id,
                "author": author,
                "policy_name": policy,
                "policy": {**POLICIES[policy],
                           "reviewer_retries_per_round": 1},
                "status": "active",
                "clean_streak": 0,
                "repair_count": 0,
                "rounds": [],
                "repairs": [],
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._save()

    def _guard_path(self) -> None:
        evidence = self.project / ".siesta"
        folder = self.path.parent
        if (evidence.is_symlink() or folder.is_symlink() or self.path.is_symlink()
                or self.path.with_suffix(".tmp").is_symlink()):
            raise ReviewError(f"review evidence path cannot be a symlink: {self.path}")

    def _read(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"),
                               object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError, ReviewError) as exc:
            raise ReviewError(f"could not read saved review state: {self.path}") from exc
        if (not isinstance(value, dict) or type(value.get("version")) is not int
                or value.get("version") != 1
                or not isinstance(value.get("status"), str)
                or value.get("status") not in {"active", "approved", "blocked"}
                or not isinstance(value.get("rounds"), list)
                or not isinstance(value.get("repairs"), list)
                or not isinstance(value.get("policy_name"), str)
                or value.get("policy_name") not in POLICIES
                or value.get("policy") != {
                    **POLICIES.get(value.get("policy_name"), {}),
                    "reviewer_retries_per_round": 1,
                }
                or not isinstance(value.get("author"), str)
                or not value["author"].strip()
                or type(value.get("repair_count")) is not int
                or value["repair_count"] != len(value["repairs"])):
            raise ReviewError(f"invalid saved review state: {self.path}")
        return value

    def _save(self) -> None:
        self._guard_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(self.path)

    def _active(self) -> None:
        if self.state["status"] != "active":
            raise ReviewError(f"review is {self.state['status']}")

    def _block(self, reason: str) -> None:
        self.state["status"] = "blocked"
        self.state["block_reason"] = reason
        self.state["updated_at"] = _now()
        self._save()

    def _current_round(self) -> dict:
        if not self.state["rounds"]:
            raise ReviewError("review has no open round")
        return self.state["rounds"][-1]

    def start_round(self, version: str) -> dict:
        """Open a round, or return its existing state when resuming it."""
        self._active()
        version = _text(version, "reviewed version", limit=256)
        if self.state["rounds"]:
            previous = self._current_round()
            if previous["status"] == "reviewing":
                if previous["version"] != version:
                    raise ReviewError("an open review round cannot change version")
                return previous
            if previous["status"] == "repaired":
                repair = self.state["repairs"][-1]
                if repair["post_version"] != version:
                    raise ReviewError("next round must review the repaired version")
                if not repair["checks_complete"]:
                    raise ReviewError("affected checks must be rerun before the next round")
            elif previous["status"] in {"findings", "insufficient_evidence"}:
                raise ReviewError("resolve findings or evidence gaps before the next round")
            elif previous["status"] not in {"clean", "disputed_resolved"}:
                raise ReviewError("previous review round is not complete")
            elif previous["status"] == "disputed_resolved" and previous["version"] != version:
                raise ReviewError("a disputed finding must be reviewed again on the same version")
        if len(self.state["rounds"]) >= self.state["policy"]["max_rounds"]:
            self._block("maximum review rounds exhausted")
            raise ReviewError("maximum review rounds exhausted")
        previous = self.state["rounds"][-1] if self.state["rounds"] else None
        if not previous or previous["version"] != version:
            self.state["clean_streak"] = 0
        round_state = {
            "number": len(self.state["rounds"]) + 1,
            "version": version,
            "status": "reviewing",
            "attempts": [],
            "report": None,
            "disputes": {},
            "opened_at": _now(),
        }
        self.state["rounds"].append(round_state)
        self.state["updated_at"] = _now()
        self._save()
        return round_state

    def begin_attempt(self, *, agent: str, context: dict,
                      retry_reason: str | None = None) -> int:
        """Persist a reviewer attempt before invoking the external model."""
        self._active()
        current = self._current_round()
        if current["status"] not in {"reviewing", "insufficient_evidence"}:
            raise ReviewError("review round is not accepting reviewer attempts")
        agent = _text(agent, "reviewer identity", limit=80)
        if agent == self.state["author"]:
            raise ReviewError("reviewer must be independent of the author")
        manifest = _validate_context(context)
        attempts = current["attempts"]
        if attempts and attempts[-1]["status"] == "running":
            attempts[-1]["status"] = "failed"
            attempts[-1]["error"] = "reviewer call did not finish before resume"
            attempts[-1]["finished_at"] = _now()
            self._save()
        if not attempts:
            if retry_reason is not None:
                raise ReviewError("the first reviewer attempt cannot be a retry")
        else:
            previous = attempts[-1]
            expected = ("expanded_context" if previous.get("outcome") == "insufficient_evidence"
                        else "reviewer_failure" if previous["status"] in {"failed", "invalid"}
                        else None)
            if expected is None or retry_reason != expected:
                raise ReviewError("review retry reason does not match the previous result")
            if expected == "expanded_context":
                old_context = previous["context"]
                if (len(set(manifest["included"]) - set(old_context["included"])) == 0
                        and len(set(old_context["omitted"]) - set(manifest["omitted"])) == 0):
                    raise ReviewError("expanded-context retry must include additional evidence")
        if len(attempts) >= MAX_REVIEW_ATTEMPTS:
            self._block("reviewer retry exhausted")
            raise ReviewError("reviewer retry exhausted")
        current["status"] = "reviewing"
        attempt = {"number": len(attempts) + 1, "agent": agent,
                   "retry_reason": retry_reason, "context": manifest,
                   "status": "running", "started_at": _now()}
        attempts.append(attempt)
        self.state["updated_at"] = _now()
        self._save()
        return attempt["number"]

    def finish_attempt(self, number: int, *, response: str | None = None,
                       error: str | None = None) -> dict | None:
        """Record an invocation outcome and validate its report before use."""
        self._active()
        current = self._current_round()
        if (not current["attempts"] or current["attempts"][-1]["number"] != number
                or current["attempts"][-1]["status"] != "running"):
            raise ReviewError("review attempt is not running")
        attempt = current["attempts"][-1]
        attempt["finished_at"] = _now()
        if error is not None:
            attempt["status"] = "failed"
            attempt["error"] = (error.strip()[:2000]
                                if isinstance(error, str) and error.strip()
                                else "reviewer call failed without details")
            self._retry_or_block(attempt)
            self._save()
            return None
        try:
            if not isinstance(response, str):
                raise ReviewError("reviewer returned no report")
            parsed = validate_report(response)
        except ReviewError as exc:
            attempt["status"] = "invalid"
            attempt["error"] = str(exc)
            _preserve_response(attempt, response)
            self._retry_or_block(attempt)
            self._save()
            return None
        attempt["status"] = "report"
        attempt["outcome"] = parsed["verdict"]
        attempt["response"] = response
        current["report"] = parsed
        if parsed["verdict"] == "pass":
            current["status"] = "clean"
            prior = self.state["rounds"][-2] if len(self.state["rounds"]) > 1 else None
            if (prior and prior["status"] == "clean" and prior["version"] == current["version"]):
                self.state["clean_streak"] += 1
            else:
                self.state["clean_streak"] = 1
            if self.state["clean_streak"] >= self.state["policy"]["clean_rounds"]:
                self.state["status"] = "approved"
                self.state["approved_version"] = current["version"]
                self.state["approved_at"] = _now()
        elif parsed["verdict"] == "findings":
            current["status"] = "findings"
            self.state["clean_streak"] = 0
            current["disputes"] = {item["id"]: {"status": "uncontested"}
                                    for item in parsed["findings"]}
        else:
            current["status"] = "insufficient_evidence"
            self.state["clean_streak"] = 0
            if number >= MAX_REVIEW_ATTEMPTS:
                self._block("review evidence remained insufficient after context expansion")
        self.state["updated_at"] = _now()
        self._save()
        return parsed

    def _retry_or_block(self, attempt: dict) -> None:
        if attempt["number"] >= MAX_REVIEW_ATTEMPTS:
            self._block("reviewer failed after its single retry")

    def record_counterevidence(self, finding_id: str, evidence: str) -> None:
        self._active()
        finding_id = _text(finding_id, "finding id", limit=80)
        current = self._current_round()
        dispute = current["disputes"].get(finding_id)
        if current["status"] != "findings" or dispute is None:
            raise ReviewError("counterevidence must refer to a current finding")
        if dispute["status"] != "uncontested":
            raise ReviewError("counterevidence was already recorded for this finding")
        dispute.update(status="pending", counterevidence=_text(evidence, "counterevidence"))
        self.state["updated_at"] = _now()
        self._save()

    def adjudicate(self, finding_id: str, *, verdict: str, agent: str,
                   evidence: str, context: dict) -> None:
        attempt = self.begin_adjudication(finding_id, agent=agent, context=context)
        self.finish_adjudication(finding_id, attempt, verdict=verdict, evidence=evidence)

    def begin_adjudication(self, finding_id: str, *, agent: str, context: dict) -> int:
        self._active()
        finding_id = _text(finding_id, "finding id", limit=80)
        current = self._current_round()
        dispute = current["disputes"].get(finding_id)
        if dispute is None or dispute["status"] != "pending":
            raise ReviewError("finding has no pending counterevidence")
        agent = _text(agent, "adjudicator identity", limit=80)
        if agent == self.state["author"]:
            raise ReviewError("adjudicator must be independent of the author")
        manifest = _validate_context(context)
        attempts = dispute.setdefault("adjudication_attempts", [])
        if attempts and attempts[-1]["status"] == "running":
            attempts[-1]["status"] = "failed"
            attempts[-1]["error"] = "adjudicator call did not finish before resume"
            attempts[-1]["finished_at"] = _now()
            self._save()
        if len(attempts) >= MAX_REVIEW_ATTEMPTS:
            self._block("adjudicator retry exhausted")
            raise ReviewError("adjudicator retry exhausted")
        attempt = {"number": len(attempts) + 1, "agent": agent, "context": manifest,
                   "status": "running", "started_at": _now()}
        attempts.append(attempt)
        self.state["updated_at"] = _now()
        self._save()
        return attempt["number"]

    def finish_adjudication(self, finding_id: str, number: int, *,
                            verdict: str | None = None, evidence: str | None = None,
                            error: str | None = None,
                            response: str | None = None) -> bool:
        self._active()
        finding_id = _text(finding_id, "finding id", limit=80)
        current = self._current_round()
        dispute = current["disputes"].get(finding_id)
        if dispute is None or dispute["status"] != "pending":
            raise ReviewError("finding has no pending counterevidence")
        attempts = dispute.get("adjudication_attempts", [])
        if (not attempts or attempts[-1]["number"] != number
                or attempts[-1]["status"] != "running"):
            raise ReviewError("adjudication attempt is not running")
        attempt = attempts[-1]
        attempt["finished_at"] = _now()
        if error is not None:
            attempt["status"] = "failed"
            attempt["error"] = (error.strip()[:2000]
                                if isinstance(error, str) and error.strip()
                                else "adjudicator call failed without details")
            if number >= MAX_REVIEW_ATTEMPTS:
                self._block("adjudicator failed after its single retry")
            else:
                self.state["updated_at"] = _now()
                self._save()
            return False
        try:
            if not isinstance(verdict, str) or verdict not in {"upheld", "dismissed"}:
                raise ReviewError("adjudication verdict must be upheld or dismissed")
            evidence = _text(evidence, "adjudication evidence")
        except ReviewError as exc:
            attempt["status"] = "invalid"
            attempt["error"] = str(exc)
            _preserve_response(attempt, response)
            if number >= MAX_REVIEW_ATTEMPTS:
                self._block("adjudicator failed after its single retry")
            else:
                self.state["updated_at"] = _now()
                self._save()
            return False
        attempt["status"] = "report"
        attempt["verdict"] = verdict
        attempt["evidence"] = evidence
        _preserve_response(attempt, response)
        dispute.update(status=verdict, adjudicator=attempt["agent"],
                       adjudication_evidence=evidence)
        if all(item["status"] == "dismissed" for item in current["disputes"].values()):
            current["status"] = "disputed_resolved"
            self.state["clean_streak"] = 0
        self.state["updated_at"] = _now()
        self._save()
        return True

    def record_repair(self, new_version: str, affected_checks: list[str], *,
                      evidence: str) -> None:
        self._active()
        current = self._current_round()
        if current["status"] != "findings":
            raise ReviewError("repairs require a findings report")
        if any(dispute["status"] == "pending" for dispute in current["disputes"].values()):
            raise ReviewError("counterevidence must be independently adjudicated before repair")
        if self.state["repair_count"] >= self.state["policy"]["max_repairs"]:
            self._block("maximum review repairs exhausted")
            raise ReviewError("maximum review repairs exhausted")
        new_version = _text(new_version, "repaired version", limit=256)
        if new_version == current["version"]:
            raise ReviewError("a repair must produce a new version")
        if (not isinstance(affected_checks, list) or not affected_checks
                or any(not isinstance(check, str) or not check.strip()
                       or "\x00" in check for check in affected_checks)):
            raise ReviewError("repair must identify unique affected checks to rerun")
        checks = [check.strip() for check in affected_checks]
        if len(checks) != len(set(checks)):
            raise ReviewError("repair must identify unique affected checks to rerun")
        unresolved = [key for key, item in current["disputes"].items()
                      if item["status"] != "dismissed"]
        if not unresolved:
            raise ReviewError("all findings were dismissed; no repair is required")
        repair = {
            "number": self.state["repair_count"] + 1,
            "round": current["number"],
            "pre_version": current["version"],
            "post_version": new_version,
            "findings": unresolved,
            "evidence": _text(evidence, "repair evidence"),
            "affected_checks": checks,
            "check_results": {},
            "checks_complete": False,
            "recorded_at": _now(),
        }
        self.state["repairs"].append(repair)
        self.state["repair_count"] += 1
        current["status"] = "repaired"
        self.state["clean_streak"] = 0
        self.state["updated_at"] = _now()
        self._save()

    def record_check(self, check: str, evidence: str, *, passed: bool) -> None:
        self._active()
        if not self.state["repairs"]:
            raise ReviewError("there is no repair requiring rechecks")
        repair = self.state["repairs"][-1]
        if repair["checks_complete"]:
            raise ReviewError("affected checks are already complete")
        check = _text(check, "check identifier", limit=256)
        if check not in repair["affected_checks"]:
            raise ReviewError(f"check is not required by this repair: {check}")
        if not isinstance(passed, bool):
            raise ReviewError("check result must explicitly say whether it passed")
        repair["check_results"].setdefault(check, []).append({
            "passed": passed, "evidence": _text(evidence, "check evidence"),
            "recorded_at": _now(),
        })
        repair["checks_complete"] = all(
            repair["check_results"].get(required)
            and repair["check_results"][required][-1]["passed"]
            for required in repair["affected_checks"])
        repair["checks_completed_at"] = _now() if repair["checks_complete"] else None
        self.state["updated_at"] = _now()
        self._save()
