"""Select project source for prompts without reading ignored or private files."""
import os
import subprocess
from pathlib import Path

EXCLUDED_DIRS = {'.git', 'kb', '.pytest_cache', '__pycache__', '.venv', 'venv',
                 'node_modules', '.runtime', '.pi', '.qwen', '.claude', '.ssh',
                 'dist', 'build', 'vendor'}


def _private(path: Path) -> bool:
    return (path.name.startswith('.env') and path.name != '.env.example'
            or path.name in {'credentials.json', 'auth.json', '.DS_Store'}
            or path.suffix in {'.pem', '.key'})


def source_files(proj: Path):
    """Include untracked product source, but never symlinks or ignored paths.

    Check ignores before descending so dependency trees do not consume the
    source budget. --no-index also excludes accidentally tracked private files.
    Plain directories (used by standalone checks) retain the explicit filters.
    """
    for root, dirs, files in os.walk(proj):
        parent = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS
                         and not _private(parent / d)
                         and not (parent / d).is_symlink())
        candidates = [parent / name for name in dirs + sorted(files)]
        if not candidates:
            continue
        names = [str(p.relative_to(proj)) for p in candidates]
        ignored = subprocess.run(
            ['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=proj,
            input='\0'.join(names) + '\0', text=True, capture_output=True,
            env={**os.environ, 'LC_ALL': 'C'})
        # Standalone checks may use plain directories. Other Git failures
        # (corrupt config, ownership checks, etc.) must not expose ignored data.
        plain_directory = (ignored.returncode == 128
                           and ignored.stderr.startswith('fatal: not a git repository')
                           and not any(os.path.lexists(p / '.git')
                                       for p in (proj.resolve(), *proj.resolve().parents)))
        if ignored.returncode not in (0, 1) and not plain_directory:
            raise RuntimeError('Cannot determine which source files are ignored: '
                               + ignored.stderr.strip())
        excluded = set(ignored.stdout.split('\0'))
        dirs[:] = [d for d in dirs if str((parent / d).relative_to(proj)) not in excluded]
        for path in candidates:
            if (str(path.relative_to(proj)) not in excluded and not _private(path)
                    and not path.is_symlink() and path.is_file()):
                yield path
