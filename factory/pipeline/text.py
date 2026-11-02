"""Pure text parsing for model output — markers, issue blocks, learning lines.

All markers are anchored at line start (re.M). The worker prompt shows
indented protocol examples, so a plain substring search would match the
prompt's own rule text; anchoring prevents that. Markdown emphasis before
the marker is tolerated (#52): models habitually bold their verdicts
(`**VERIFY_PASSED:**`), and run #25 lost a QA verdict that way.
"""
import re

# Optional leading markdown decoration a model may put before a marker:
# heading hashes or bold/italic emphasis, with any spacing after it
# (#52: `**VERIFY_PASSED:**`, `### APPROVED` must not fall to fallbacks).
# Bare indentation is NOT decoration — the prompt's own indented rule
# examples must keep not matching (see the anchor tests). Closing emphasis
# after the colon does not matter — the regexes match the prefix only.
_DECOR = r"(?:#{1,6}[ \t]+)?(?:[*_]{1,4}[ \t]*)?"

INTENT = re.compile(
    rf"^{_DECOR}INTENT_FINALIZED:[ \t]*(?:[*_]{{1,4}}[ \t]*)?(.+)$", re.M)
ISSUE_HDR = re.compile(r"^##[ \t]+Issue[ \t]+#(\d+)", re.M)
CONSULT = re.compile(rf"^{_DECOR}CONSULT:", re.M)
PROXY = re.compile(rf"^{_DECOR}PROXY_REQUEST:", re.M)
SKIP = re.compile(rf"^{_DECOR}SKIP:", re.M)
CRITICAL = re.compile(rf"^{_DECOR}CRITICAL:", re.M)
REJECTED = re.compile(rf"^(?:{_DECOR}PROXY_DECISION:[ \t]*)?{_DECOR}REJECTED\b", re.M)
NEEDS_REVISION = re.compile(rf"^(?:{_DECOR}PROXY_DECISION:[ \t]*)?{_DECOR}NEEDS_REVISION\b", re.M)
# Explicit approval only (#3): "APPROVED" at line start, optionally after the
# skill's own "PROXY_DECISION:" prefix. Hesitation, NEEDS_REVISION or garbage
# do not match — gates treat no explicit approval as "not approved".
APPROVED = re.compile(rf"^(?:{_DECOR}PROXY_DECISION:[ \t]*)?{_DECOR}APPROVED\b", re.M)
REVIEW_PASSED = re.compile(rf"^{_DECOR}REVIEW_PASSED:", re.M)
REVIEW_FAILED = re.compile(rf"^{_DECOR}REVIEW_FAILED:", re.M)
VERIFY_PASSED = re.compile(rf"^{_DECOR}VERIFY_PASSED:", re.M)
VERIFY_FAILED = re.compile(rf"^{_DECOR}VERIFY_FAILED:", re.M)

# "TAG: summary — detail", split at the FIRST dash separator so details may
# themselves contain dashes. Models emit "-", "–" and "—" interchangeably (#14),
# and a summary-only line is still worth logging — so all three separators are
# accepted and the detail is optional. Learner Actions lines are indented by
# design (unlike the worker protocol markers above), so allow leading tabs/spaces.
LEARN = re.compile(
    r"^[ \t]*(LEARNING|SKILL_IMPROVEMENT|NEW_SKILL):[ \t]*(.+?)"
    r"(?:[ \t]+[—–-][ \t]+(.+))?$", re.M
)
SKILL_START = re.compile(r"^SKILL_UPDATE_START:[ \t]*(\S+)[ \t]*$")
MARKDOWN_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


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
    """Read actions outside quoted examples and skill replacement bodies."""
    prose, _ = _learning_parts(output)
    return [(kind, summary.strip(), (detail or "").strip())
            for kind, summary, detail in LEARN.findall(prose)]


def skill_updates(output: str) -> list[tuple[str, str]]:
    """Preserve complete Markdown bodies, including their literal examples."""
    return _learning_parts(output)[1]


def _learning_parts(output: str) -> tuple[str, list[tuple[str, str]]]:
    prose, updates, body = [], [], []
    name = None
    for raw, fenced in _fenced_lines(output):
        line = raw.rstrip('\r\n')
        if fenced:
            if name is not None:
                body.append(line)
            continue
        start = SKILL_START.match(line)
        if name is not None:
            if start:
                # Unquoted nesting makes the outer boundary ambiguous. Discard
                # the unfinished block and remainder rather than execute it.
                break
            if line.rstrip() == "SKILL_UPDATE_END":
                updates.append((name, "\n".join(body).strip("\n")))
                name, body = None, []
            else:
                body.append(line)
        elif start:
            name = start[1]
        else:
            prose.append(line)
    # An unfinished replacement is neither a file update nor a set of actions.
    return "\n".join(prose), updates


def head(text: str, n: int) -> str:
    """First n lines (replaces `head -N`)."""
    return "\n".join(text.splitlines()[:n])


# Glue words that appear in any text and prove nothing about relevance.
_STOP = {"this", "that", "with", "from", "have", "will", "your", "when",
         "must", "should", "each", "their", "which", "about", "into"}


def content_words(s: str) -> set[str]:
    """Lowercase words of 4+ letters, minus glue words."""
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())} - _STOP


def shares_content(a: str, b: str) -> bool:
    """Require up to two shared content words between intent and document.
    A single generic word is weak evidence of relevance. Short intents need
    only as many matches as they contain; empty intents cannot be judged."""
    words_a = content_words(a)
    return len(words_a & content_words(b)) >= min(2, len(words_a))


# ─── Document extraction (spec/plan output protocol) ─────────────────────
# Models run with --no-tools in phases 1-2: they output the document as
# text and the pipeline saves it. Models with narration habits fence the
# document or add a prologue — both are stripped here.

HEADING = re.compile(r"^#{1,6}[ \t]+\S", re.M)
BARE_FENCE = re.compile(r"^[ \t]*```[ \t]*$")
TAGGED_FENCE = re.compile(r"^[ \t]*```(\w[\w+-]*)[ \t]*$")
# Fence tags that mean "the fenced region is a document, not code": kept as
# content (an enclosing ```markdown wrapper is narration, handled by
# unwrap_fences). Any other tag means a code example — cut before parsing.
DOC_FENCE_TAGS = {"markdown", "md", "text"}


def unwrap_fences(out: str) -> str:
    """Strip a single enclosing ``` fence, if present."""
    s = out.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1 and s.endswith("```"):
            return s[first_nl + 1:-3].strip()
    return s


def _fence_tag(line: str) -> str | None:
    """Language tag of a tagged fence line, lowercased; None if not one."""
    m = TAGGED_FENCE.match(line)
    return m.group(1).lower() if m else None


def _strip_code_fences(doc: str) -> str:
    """Remove code examples before checking document headings.
    Bare fences and Markdown/text wrappers contain prose and are preserved."""
    lines, cutting = [], False
    for line in doc.splitlines():
        if cutting:
            if BARE_FENCE.match(line):
                cutting = False
            continue
        tag = _fence_tag(line)
        if tag is not None and tag not in DOC_FENCE_TAGS:
            cutting = True
            continue
        lines.append(line)
    return "\n".join(lines)


def _fenced_lines(out: str):
    """Yield original lines with their Markdown-fence membership."""
    fence = None
    for line in out.splitlines(keepends=True):
        boundary = MARKDOWN_FENCE.match(line.rstrip('\r\n'))
        fenced = fence is not None or boundary is not None
        if fence:
            if (boundary and boundary[1][0] == fence[0]
                    and len(boundary[1]) >= len(fence) and not boundary[2].strip()):
                fence = None
        elif boundary:
            fence = boundary[1]
        yield line, fenced


def without_fences(out: str) -> str:
    """Mask fenced examples while preserving offsets into the original output.

    Only real markers authorize actions. Matching offsets let callers forward
    the associated raw code/error evidence without treating it as a signal.
    An unclosed fence masks all remaining content.
    """
    return ''.join(re.sub(r'[^\r\n]', ' ', line) if fenced else line
                   for line, fenced in _fenced_lines(out))


def spec_doc(out: str) -> str | None:
    """Model output -> spec.md content; None if it is not a plain document.

    Tagged code-fence regions are cut before the heading check (#36): a
    spec with a small ```python example parses, but fenced lines never
    reach the saved doc. An answer fenced whole as code is a dump — the
    cut leaves nothing, so it is rejected. Bare fenced prose blocks and
    ```markdown-style wrappers are kept as illustration.
    """
    doc = unwrap_fences(_strip_code_fences(out)).strip()
    if not doc:
        return None
    return doc if HEADING.search(doc) else None


def issues_doc(out: str) -> str | None:
    """Model output -> issues.md content starting at the first '## Issue'."""
    doc = unwrap_fences(out)
    m = ISSUE_HDR.search(doc)
    return doc[m.start():].strip() if m else None
