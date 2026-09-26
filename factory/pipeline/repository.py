"""Git-backed completion records and product identity for safe resumes."""
import hashlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

from pipeline import text


def git(proj: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=proj, capture_output=True)


def checked_git(proj: Path, *args: str) -> bytes:
    result = git(proj, *args)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode(errors='replace').strip()
        raise RuntimeError(f"Git {' '.join(args[:2])} failed: {detail}")
    return result.stdout


def commit(proj: Path, message: str) -> str:
    completed_issues(proj)
    checked_git(proj, 'add', '-A')
    before = fingerprint(proj)
    changed = git(proj, 'diff', '--cached', '--quiet')
    if changed.returncode not in (0, 1):
        raise RuntimeError('Cannot inspect staged changes before commit')
    if changed.returncode:
        checked_git(proj, 'commit', '-m', message)
    if fingerprint(proj) != before:
        raise RuntimeError('Product changed during commit; review and verification are required again')
    require_clean(proj)
    return checked_git(proj, 'rev-parse', 'HEAD').decode().strip()


@contextmanager
def completion_record(proj: Path, kb):
    """Roll back a completion claim (including its index copy) on commit failure."""
    before = kb.path.read_bytes()
    head = checked_git(proj, 'rev-parse', 'HEAD')
    try:
        yield
    except BaseException:
        kb.path.write_bytes(before)
        kb._reload()
        checked_git(proj, 'add', '--', str(kb.path.relative_to(proj)))
        if checked_git(proj, 'rev-parse', 'HEAD') != head:
            checked_git(proj, 'commit', '--only', '-m',
                        'Withdraw unsuccessful completion record', '--',
                        str(kb.path.relative_to(proj)))
        raise


def issue_digest(body: str) -> str:
    return hashlib.sha256(body.strip().encode()).hexdigest()


def read_plan(proj: Path) -> dict[int, str]:
    return parse_plan((proj / 'issues.md').read_text())


def parse_plan(content: str) -> dict[int, str]:
    # Ignore example headers inside fences while retaining the complete body
    # (including acceptance code) in the immutable requirement digest.
    headers = []
    offset = 0
    fence = None
    for line in content.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            match = text.ISSUE_HDR.match(line)
            if match:
                headers.append((int(match[1]), offset, offset + match.end()))
        offset += len(line)
    issues = {}
    for index, (num, start, end) in enumerate(headers):
        if num in issues:
            raise RuntimeError(f'Duplicate issue #{num}; use unique issue numbers')
        next_start = headers[index + 1][1] if index + 1 < len(headers) else len(content)
        issues[num] = content[end:next_start].strip()
    if not issues:
        raise RuntimeError('Plan contains no issues')
    return issues


def committed_nodes(proj: Path) -> list[dict]:
    saved = git(proj, 'show', 'HEAD:kb/graph.json')
    if saved.returncode:
        return []
    return json.loads(saved.stdout)['nodes']


def _legacy_issue_digest(proj: Path, node_id: str, num: int) -> str:
    history = checked_git(proj, 'log', '--reverse', '--format=%H', '--', 'kb/graph.json')
    for revision in history.decode().splitlines():
        saved = git(proj, 'show', f'{revision}:kb/graph.json')
        if saved.returncode:
            continue
        if any(node['id'] == node_id for node in json.loads(saved.stdout)['nodes']):
            plan = checked_git(proj, 'show', f'{revision}:issues.md').decode()
            issues = parse_plan(plan)
            if num in issues:
                return issue_digest(issues[num])
            break
    raise RuntimeError(f'Cannot reconcile completed issue #{num} with its committed plan')


def completed_issues(proj: Path) -> set[int]:
    """Read only committed claims; completed requirements cannot be rewritten."""
    nodes = committed_nodes(proj)
    if not (proj / 'issues.md').exists():
        if any(node['type'] == 'decision' and re.fullmatch(
                r'Issue #\d+ completed', node['summary']) for node in nodes):
            raise RuntimeError('Cannot remove the completed issue plan; restore issues.md '
                               'and add a new issue or use --iterate')
        return set()
    issues = read_plan(proj)
    completed = set()
    for node in nodes:
        match = re.fullmatch(r'Issue #(\d+) completed', node['summary'])
        if node['type'] != 'decision' or not match:
            continue
        num = int(match[1])
        try:
            detail = json.loads(node['detail'])
        except (ValueError, TypeError):
            detail = {}
        digest = detail.get('issue_sha256') if isinstance(detail, dict) else None
        if not digest:
            digest = _legacy_issue_digest(proj, node['id'], num)
        if num not in issues or issue_digest(issues[num]) != digest:
            raise RuntimeError(f'Cannot change or remove completed issue #{num}; '
                               'restore it and add a new issue or use --iterate')
        completed.add(num)
    return completed


def require_clean(proj: Path) -> None:
    # KB learning may remain uncommitted between issues. It is bookkeeping;
    # product edits, including untracked files, always require explicit adoption.
    status = checked_git(proj, 'status', '--porcelain', '-z', '--untracked-files=all',
                         '--', '.', ':(exclude)kb')
    if status:
        raise RuntimeError('Uncommitted product changes preserved. Commit them or use '
                           '--adopt-changes before resuming; no files were discarded.')


def require_committed_ledger(proj: Path) -> None:
    path = proj / 'kb/graph.json'
    if not path.exists():
        return

    def completions(nodes):
        return {node['id']: node for node in nodes if node['type'] == 'decision' and (
            re.fullmatch(r'Issue #\d+ completed', node['summary'])
            or node['summary'].startswith('Project complete:')
            or node['summary'] == 'Iteration request')}

    if completions(json.loads(path.read_text())['nodes']) != completions(committed_nodes(proj)):
        raise RuntimeError('Uncommitted changes to the completion ledger; preserve the KB '
                           'and reconcile it with HEAD before resuming or adopting changes')


def adopt_changes(proj: Path) -> None:
    require_committed_ledger(proj)
    completed_issues(proj)
    commit(proj, 'Adopt local changes for Siesta')


def fingerprint(proj: Path) -> str:
    """Identify product bytes, paths and executable modes, independently of KB."""
    names = checked_git(proj, 'ls-files', '-z', '--cached', '--others',
                        '--exclude-standard', '--', '.', ':(exclude)kb')
    digest = hashlib.sha256()
    for name in sorted(set(names.split(b'\0')) - {b''}):
        path = proj / os.fsdecode(name)
        digest.update(name + b'\0')
        if path.is_symlink():
            digest.update(b'link\0' + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b'executable\0' if path.stat().st_mode & 0o111 else b'file\0')
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(65536), b''):
                    digest.update(chunk)
        else:
            raise RuntimeError(f'Product path missing or unsupported: {os.fsdecode(name)}')
        digest.update(b'\0')
    return digest.hexdigest()


def state_path(proj: Path) -> Path:
    git_dir = checked_git(proj, 'rev-parse', '--absolute-git-dir').decode().strip()
    return Path(git_dir) / 'siesta-state.json'


def load_state(proj: Path) -> dict:
    path = state_path(proj)
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(proj: Path, state: dict) -> None:
    path = state_path(proj)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state) + '\n')
    temp.replace(path)
