"""Plan an additional request without rewriting completed issue requirements."""
import json
from pathlib import Path

from pipeline import phases, repository, text
from pipeline.pi import SKILLS, log, run_pi

REQUEST_SUMMARY = 'Iteration request'


def latest_request(proj: Path) -> dict | None:
    records = [node for node in repository.committed_nodes(proj)
               if node['type'] == 'decision' and node['summary'] == REQUEST_SUMMARY]
    return json.loads(records[-1]['detail']) if records else None


def prepare(proj: Path, request: str, kb) -> None:
    request = request.strip()
    previous = latest_request(proj)
    if previous and previous['request'] == request:
        log('Iteration request already recorded — resuming its existing work')
        return
    old_issues = repository.read_plan(proj)
    completed = repository.completed_issues(proj)
    checkpoint = proj / '.pipeline-checkpoint'
    if (set(old_issues) != completed or not checkpoint.exists()
            or checkpoint.read_text().strip() != 'complete'):
        raise RuntimeError('Finish the active work with --resume before starting a different iteration')
    repository.require_clean(proj)
    old_spec = (proj / 'spec.md').read_text()
    old_plan = (proj / 'issues.md').read_text()
    intent = kb.query(type_='intent')[0]['detail']
    context = (
        'The human has left. Do not ask questions. You have no tools.\n'
        f'Original intent:\n{intent}\n\nCurrent specification:\n{old_spec}\n\n'
        f'Existing issues (immutable):\n{old_plan}\n\n'
        f'Additional request:\n{request}\n\n'
        f'Current source:\n{phases.gather(proj)}\n')
    spec = _amendment(proj, context, request)
    first = max(old_issues) + 1
    plan = _plan(proj, context, spec, first)
    additions = repository.parse_plan(plan)
    # The old documents survive generation errors and commit hooks. Model
    # outputs remain in their ignored artifacts for inspection and retry.
    paths = ('spec.md', 'issues.md')
    try:
        with repository.completion_record(proj, kb):
            (proj / 'spec.md').write_text(
                old_spec.rstrip() + '\n\n# Iteration amendment\n\n' + spec + '\n')
            (proj / 'issues.md').write_text(old_plan.rstrip() + '\n\n' + plan + '\n')
            spec_node = kb.node('spec', 'Iteration specification', spec)
            for num, body in additions.items():
                node = kb.node('issue', f'Issue #{num}', body)
                kb.edge(node, spec_node, 'parent_of')
            kb.node('decision', REQUEST_SUMMARY, json.dumps({
                'request': request, 'issues': list(additions),
            }))
            repository.commit(proj, f'Plan iteration: issues #{first}–#{max(additions)}')
    except BaseException:
        (proj / 'spec.md').write_text(old_spec)
        (proj / 'issues.md').write_text(old_plan)
        repository.checked_git(proj, 'add', '--', *paths)
        raise
    checkpoint.write_text('phase-2\n')
    (proj / 'verify_verdict.txt').unlink(missing_ok=True)
    repository.save_state(proj, {})
    log(f'Iteration planned: {len(additions)} new issues, starting at #{first}')


def _amendment(proj: Path, context: str, request: str) -> str:
    directive = ('ITERATION_SPEC: Output only a Markdown specification amendment '
                 'with requirements and acceptance criteria for the additional request. '
                 'Preserve existing behavior unless the request explicitly changes it. '
                 'Do not implement code.')
    for attempt in range(2):
        output = run_pi(
            'planner', context, directive,
            skills=(SKILLS / 'spec-driven-development',), tools='no', cwd=proj,
            artifact=proj / f'iteration_spec_{attempt}_output.txt')
        doc = text.spec_doc(output)
        if doc and text.shares_content(request, doc):
            return doc
        directive = ('ITERATION_SPEC: Previous output was invalid or unrelated. '
                     'Return only the Markdown specification amendment for the request, '
                     'with concrete acceptance criteria. No code, questions or tool calls.')
    raise RuntimeError('Iteration specification rejected after two attempts; previous plan preserved')


def _plan(proj: Path, context: str, spec: str, first: int) -> str:
    directive = (f'ITERATION_PLAN: Output only NEW issues beginning with ## Issue #{first}: Title. '
                 'Use consecutive unique numbers. Each issue must specify behavior, acceptance '
                 'criteria, dependencies and meaningful tests. Never rewrite old issues. No code.')
    for attempt in range(2):
        output = run_pi(
            'planner', context + '\nSpecification amendment:\n' + spec, directive,
            skills=(SKILLS / 'planning-and-task-breakdown',), tools='no', cwd=proj,
            artifact=proj / f'iteration_plan_{attempt}_output.txt')
        doc = text.issues_doc(output)
        try:
            issues = repository.parse_plan(doc or '')
            if list(issues) == list(range(first, first + len(issues))):
                return doc
        except RuntimeError:
            pass
        directive = (f'ITERATION_PLAN: Previous output was rejected. Start at ## Issue #{first}: Title '
                     'and use consecutive unique numbers, only new issues with tests. No code.')
    raise RuntimeError('Iteration plan rejected after two attempts; previous plan preserved')

