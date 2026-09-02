"""Pure text parsing for model output — markers, issue blocks, learning lines.

All markers are anchored at line start (re.M). The worker prompt shows
indented protocol examples, so a plain substring search would match the
prompt's own rule text; anchoring prevents that.
"""
import re

INTENT = re.compile(r"^INTENT_FINALIZED:[ \t]*(.+)$", re.M)
ISSUE_HDR = re.compile(r"^##[ \t]+Issue[ \t]+#(\d+)", re.M)
CONSULT = re.compile(r"^CONSULT:", re.M)
PROXY = re.compile(r"^PROXY_REQUEST:", re.M)
SKIP = re.compile(r"^SKIP:", re.M)
CRITICAL = re.compile(r"^CRITICAL:", re.M)
REJECTED = re.compile(r"^REJECTED:", re.M)
# Explicit approval only (#3): "APPROVED" at line start, optionally after the
# skill's own "PROXY_DECISION:" prefix. Hesitation, NEEDS_REVISION or garbage
# do not match — gates treat no explicit approval as "not approved".
APPROVED = re.compile(r"^(?:PROXY_DECISION:[ \t]*)?APPROVED\b", re.M)
REVIEW_PASSED = re.compile(r"^REVIEW_PASSED:", re.M)
REVIEW_FAILED = re.compile(r"^REVIEW_FAILED:", re.M)
VERIFY_PASSED = re.compile(r"^VERIFY_PASSED:", re.M)
VERIFY_FAILED = re.compile(r"^VERIFY_FAILED:", re.M)

# "TAG: summary — detail", split at the FIRST dash separator so details may
# themselves contain dashes. Models emit "-", "–" and "—" interchangeably (#14),
# and a summary-only line is still worth logging — so all three separators are
# accepted and the detail is optional. Learner Actions lines are indented by
# design (unlike the worker protocol markers above), so allow leading tabs/spaces.
LEARN = re.compile(
    r"^[ \t]*(LEARNING|SKILL_IMPROVEMENT|NEW_SKILL):[ \t]*(.+?)"
    r"(?:[ \t]+[—–-][ \t]+(.+))?$", re.M
)
SKILL_BLOCK = re.compile(
    r"^[ \t]*SKILL_UPDATE_START:[ \t]*(\S+)[ \t]*\n(.*?)^[ \t]*SKILL_UPDATE_END",
    re.M | re.S,
)


# ─── Degenerate-output guard (silence is not success) ─────────────────────
# Live runs showed models returning tool-call JSON instead of protocol text
# and asking the absent human for input. Those outputs are not answers: the
# gates in phases.py treat them as failed attempts, never as success (#2,
# #11, #12). Not applied to the interactive interview, where questions to
# the human are the whole point.

TOOL_SPEAK = re.compile(r'\{\s*"name"\s*:[^}]*"arguments"|"tool_calls"')
ASKS_HUMAN = re.compile(
    r"(?i)\b(please provide|once you provide|could you (?:tell|provide|clarify)"
    r"|what would you like|i need (?:more )?information)\b")


def degenerate(output: str) -> str | None:
    """Why the output cannot be a real answer; None if it looks usable.

    Near-empty bodies, tool-call JSON narration and questions aimed at the
    absent human mean the phase never got an answer.
    """
    body = output.strip()
    if len(body) < 40:
        return "too short to be a real answer"
    if TOOL_SPEAK.search(body):
        return "tool-call JSON narration, not protocol text"
    if ASKS_HUMAN.search(body):
        return "asks the absent human for input"
    return None


def split_issues(issues_md: str) -> list[tuple[int, str]]:
    """Return [(number, body), ...] for each '## Issue #N' section, in order."""
    found = list(ISSUE_HDR.finditer(issues_md))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(issues_md)
        out.append((int(m.group(1)), issues_md[m.end():end].strip()))
    return out


def after(source: str, match: re.Match, span: int = 50) -> str:
    """The matched line plus the next `span` lines (replaces `grep -A N`)."""
    return "\n".join(source[match.start():].splitlines()[: span + 1])


def intent_from(output: str, idea: str) -> str:
    """Interview output -> final intent; falls back to the raw idea.

    Keeps the marker line plus the rest of its paragraph, like the bash
    `grep -A 50 | sed` extraction, stopping at the first blank line.
    """
    m = INTENT.search(output)
    if not m:
        return idea
    lines = [m.group(1)]
    # `$` is zero-width: the remainder starts with the newline that ended
    # the marker line, so splitlines() yields one empty line first.
    for line in output[m.end():].splitlines()[1:]:
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines).strip()


def learnings(output: str) -> list[tuple[str, str, str]]:
    """Return (kind, summary, detail) for every learning-style line."""
    return [(kind, summary.strip(), (detail or "").strip())
            for kind, summary, detail in LEARN.findall(output)]


def skill_updates(output: str) -> list[tuple[str, str]]:
    """Return (skill_name, replacement_body) for SKILL_UPDATE_START/END blocks."""
    return [(name.replace("/", ""), body.strip("\n"))
            for name, body in SKILL_BLOCK.findall(output)]


def head(text: str, n: int) -> str:
    """First n lines (replaces `head -N`)."""
    return "\n".join(text.splitlines()[:n])


# ─── Document extraction (spec/plan output protocol) ─────────────────────
# Models run with --no-tools in phases 1-2: they output the document as
# text and the pipeline saves it. Models with narration habits fence the
# document or add a prologue — both are stripped here.

HEADING = re.compile(r"^#{1,6}[ \t]+\S", re.M)


def unwrap_fences(out: str) -> str:
    """Strip a single enclosing ``` fence, if present."""
    s = out.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1 and s.endswith("```"):
            return s[first_nl + 1:-3].strip()
    return s


def spec_doc(out: str) -> str | None:
    """Model output -> spec.md content; None if it is not a plain document.

    A fenced block anywhere means the model dumped code (run #4 smuggled a
    whole program whose ```python body contained a '###' heading). A spec is
    prose; reject anything with a live fence after unwrapping the outer one.
    """
    doc = unwrap_fences(out).strip()
    if "```" in doc:
        return None
    return doc if HEADING.search(doc) else None


def issues_doc(out: str) -> str | None:
    """Model output -> issues.md content starting at the first '## Issue'."""
    doc = unwrap_fences(out)
    m = ISSUE_HDR.search(doc)
    return doc[m.start():].strip() if m else None