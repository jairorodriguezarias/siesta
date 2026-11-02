"""Independent comparison of a candidate intent with user-provided evidence."""
import json
from pathlib import Path

from pipeline.files import evidence_dir


class IntentReviewError(RuntimeError):
    """The intent critic could not return a valid evidence-based decision."""


class IntentDecisionRequired(RuntimeError):
    """A new product decision must come from the user before specification."""


PROMPT = """Independently compare the candidate intent with the original request.
Do not generate a specification. The original request and explicit answers
are the evidence for what the user wants. Do not treat rejected or unconfirmed
drafts as decisions. Find omitted requirements, contradictions, or scope the
candidate added without support.

Original request:
{original}

Explicit human answers:
{answers}

Interview transcript (context only; rejected drafts are marked):
{transcript}

Candidate intent:
{candidate}

If the candidate is complete and supported, return verdict "pass" and leave it
unchanged. If existing evidence resolves an omission or contradiction, return
"revised", quote an exact substring from the original request or an explicit
answer for each correction, and provide the corrected candidate. If deciding
would require a preference not stated by the user, return "blocked" and name
the question and why the evidence cannot resolve it. A report may include both
evidence-grounded corrections and unresolved questions, but unresolved
questions always block specification generation.

Return exactly one JSON object, with no prose or code fence:

For pass:
{{"version":1,"verdict":"pass","changes":[],"unresolved":[]}}

For revised:
{{"version":1,"verdict":"revised","candidate":"...","changes":[{{"id":"C1","issue":"...","evidence":"exact quote from request or answer","resolution":"..."}}],"unresolved":[]}}

For blocked:
{{"version":1,"verdict":"blocked","candidate":"...","changes":[],"unresolved":[{{"id":"U1","question":"...","reason":"...","options":["...","..."]}}]}}

Change objects have exactly id, issue, evidence, resolution. Unresolved objects
have exactly id, question, reason, options. Do not invent evidence or decide
for the user."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate field: {key}")
        value[key] = item
    return value


def _nonempty(value, label: str, *, limit: int = 8000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must be nonempty and at most {limit} characters")
    return value.strip()


def _list(value, label: str, *, maximum: int = 30) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be a list of at most {maximum} items")
    return value


def validate_report(output: str, *, original: str, explicit_answers: list[str],
                    current_candidate: str) -> dict:
    """Parse and validate the critic contract and exact evidence quotes."""
    if not isinstance(output, str) or len(output) > 128_000:
        raise IntentReviewError("intent review report is missing or too large")
    try:
        value = json.loads(output, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise IntentReviewError("intent review response is not valid unique-key JSON") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int \
            or value.get("version") != 1:
        raise IntentReviewError("intent review report has an invalid version or shape")
    verdict = value.get("verdict")
    evidence = "\n".join([original, *explicit_answers])
    allowed_change_keys = {"id", "issue", "evidence", "resolution"}
    allowed_unresolved_keys = {"id", "question", "reason", "options"}

    def validate_changes(items) -> list[dict]:
        items = _list(items, "changes")
        seen = set()
        normalized = []
        for item in items:
            if not isinstance(item, dict) or set(item) != allowed_change_keys:
                raise IntentReviewError("each correction needs id, issue, evidence and resolution")
            identifier = _nonempty(item["id"], "correction id", limit=80)
            quote = _nonempty(item["evidence"], "evidence quote", limit=2000)
            if identifier in seen:
                raise IntentReviewError("correction IDs must be unique")
            if quote not in evidence:
                raise IntentReviewError("correction evidence must quote the request or an explicit answer")
            seen.add(identifier)
            normalized.append({
                "id": identifier,
                "issue": _nonempty(item["issue"], "correction issue"),
                "evidence": quote,
                "resolution": _nonempty(item["resolution"], "correction resolution"),
            })
        return normalized

    def validate_unresolved(items) -> list[dict]:
        items = _list(items, "unresolved decisions")
        seen = set()
        normalized = []
        for item in items:
            if not isinstance(item, dict) or set(item) != allowed_unresolved_keys:
                raise IntentReviewError("each unresolved decision needs id, question, reason and options")
            identifier = _nonempty(item["id"], "unresolved decision id", limit=80)
            if identifier in seen:
                raise IntentReviewError("unresolved decision IDs must be unique")
            seen.add(identifier)
            options = _list(item["options"], "decision options", maximum=8)
            if any(not isinstance(option, str) or not option.strip() or len(option) > 500
                   for option in options):
                raise IntentReviewError("decision options must be nonempty strings")
            normalized.append({
                "id": identifier,
                "question": _nonempty(item["question"], "user decision question"),
                "reason": _nonempty(item["reason"], "decision evidence gap"),
                "options": [option.strip() for option in options],
            })
        return normalized

    if verdict == "pass":
        if set(value) != {"version", "verdict", "changes", "unresolved"}:
            raise IntentReviewError("pass report has unexpected fields")
        changes = validate_changes(value["changes"])
        unresolved = validate_unresolved(value["unresolved"])
        if changes or unresolved:
            raise IntentReviewError("pass report cannot contain corrections or open decisions")
        return {"version": 1, "verdict": "pass", "candidate": current_candidate,
                "changes": [], "unresolved": []}
    if verdict not in {"revised", "blocked"} or set(value) != {
            "version", "verdict", "candidate", "changes", "unresolved"}:
        raise IntentReviewError("intent review report has an unsupported verdict or shape")
    candidate = _nonempty(value["candidate"], "reviewed candidate intent")
    changes = validate_changes(value["changes"])
    unresolved = validate_unresolved(value["unresolved"])
    if verdict == "revised":
        if not changes or unresolved or candidate == current_candidate:
            raise IntentReviewError("revised intent needs a grounded change and no unresolved decision")
    elif not unresolved:
        raise IntentReviewError("blocked intent needs at least one explicit user decision")
    return {"version": 1, "verdict": verdict, "candidate": candidate,
            "changes": changes, "unresolved": unresolved}


def _save(path: Path, value: dict) -> None:
    if path.parent.is_symlink() or path.is_symlink() or path.with_suffix(".tmp").is_symlink():
        raise IntentReviewError("intent review evidence path cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def review_intent(project: Path, original: str, transcript: str, candidate: str,
                  human_confirmed: bool, kb, *, explicit_answers: list[str],
                  run_pi) -> str:
    """Return an approved intent or record why specification must stop."""
    project = Path(project)
    evidence = project / ".siesta"
    if evidence.is_symlink():
        raise IntentReviewError("intent review evidence directory cannot be a symlink")
    path = evidence_dir(project) / "intent-review.json"
    if (not isinstance(explicit_answers, list) or len(explicit_answers) > 100
            or any(not isinstance(answer, str) or not answer.strip()
                   or len(answer) > 8000 for answer in explicit_answers)):
        raise IntentReviewError("explicit human answers have an invalid shape")
    answers = [answer.strip() for answer in explicit_answers]
    body = PROMPT.format(
        original=original,
        answers="\n".join(f"- {answer}" for answer in answers) or "(none)",
        transcript=transcript or "(none)",
        candidate=candidate,
    )
    attempts = []
    validated = None
    for attempt in range(2):
        raw = ""
        try:
            raw = run_pi(
                "consultant", body,
                "Review the candidate intent against the request and answers",
                tools="no", isolated=True, agent="intent-critic",
                context_kind="intent_review", cwd=project,
                artifact=evidence / "intent-critic.txt", phase_name="intent_review")
            validated = validate_report(raw, original=original,
                                        explicit_answers=answers,
                                        current_candidate=candidate)
            attempts.append({"number": attempt + 1, "status": "valid",
                             "response": raw})
            break
        except Exception as exc:
            attempts.append({"number": attempt + 1, "status": "failed",
                             "error": str(exc)[:2000],
                             "response": raw if "raw" in locals() and isinstance(raw, str) else ""})
            raw = None

    if validated is None:
        record = {"version": 1, "status": "invalid", "human_confirmed": human_confirmed,
                  "original_request": original, "explicit_answers": answers,
                  "transcript": transcript, "candidate_before": candidate,
                  "attempts": attempts}
        _save(path, record)
        detail = json.dumps(record, sort_keys=True)
        kb.node("blocker", "Intent review failed", detail)
        failure = attempts[-1]["error"] if attempts else "no answer"
        raise IntentReviewError(f"intent critic failed to produce a valid report: {failure}")

    record = {"version": 1, "status": validated["verdict"],
              "human_confirmed": human_confirmed,
              "original_request": original, "explicit_answers": answers,
              "transcript": transcript, "candidate_before": candidate,
              "candidate_after": validated["candidate"],
              "changes": validated["changes"],
              "unresolved": validated["unresolved"], "attempts": attempts}
    _save(path, record)
    if validated["verdict"] == "blocked":
        detail = json.dumps(record, indent=2, sort_keys=True)
        kb.node("blocker", "Intent review needs user decision", detail)
        questions = "; ".join(item["question"] for item in validated["unresolved"])
        raise IntentDecisionRequired(questions)
    return validated["candidate"]
