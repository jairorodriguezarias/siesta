"""Local display names for generated projects; Git root identity stays stable."""
import os
from pathlib import Path

NAME_FILE = '.siesta/display-name.txt'


def validate_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Project name must be text')
    name = value.strip()
    if (not 1 <= len(name) <= 80
            or any(character in '/\\' or not character.isprintable()
                   for character in name)):
        raise ValueError('Project name must be 1–80 characters without paths or line breaks')
    return name


def read_name(project: Path, fallback: str) -> str:
    path = Path(project) / NAME_FILE
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeError('Project name path cannot be a symlink')
    if not path.is_file():
        return fallback
    return validate_name(path.read_text(encoding='utf-8'))


def write_name(project: Path, value: str) -> str:
    name = validate_name(value)
    path = Path(project) / NAME_FILE
    temporary = path.with_suffix('.tmp')
    if path.parent.is_symlink() or path.is_symlink() or temporary.is_symlink():
        raise RuntimeError('Project name path cannot be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(name + '\n', encoding='utf-8')
    os.replace(temporary, path)
    return name
