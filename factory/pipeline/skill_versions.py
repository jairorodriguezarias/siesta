"""Per-project snapshots of the skills available to a Siesta execution."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

MANIFEST_NAME = "skill-versions.json"
SNAPSHOT_VERSION = 1
_SAFE_SKILL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def source_roots() -> dict[str, Path]:
    # Import lazily: pi delegates skill path resolution here at call time.
    from pipeline import pi
    return {"factory": pi.FACTORY_SKILLS, "adapted": pi.SKILLS}


def _safe_storage(project: Path) -> Path:
    project = Path(project)
    if project.is_symlink():
        raise RuntimeError("project directory cannot be a symlink for skill pinning")
    evidence = project / ".siesta"
    if evidence.is_symlink():
        raise RuntimeError(".siesta cannot be a symlink for skill pinning")
    evidence.mkdir(parents=True, exist_ok=True)
    return evidence


def _tree_hash(directory: Path) -> tuple[str, dict[str, str]]:
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"skill snapshots cannot contain symlinks: {path}")
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return digest, files


def _inventory(roots: dict[str, Path]) -> list[tuple[str, str, Path]]:
    entries = []
    for scope in ("factory", "adapted"):
        original_root = Path(roots[scope])
        if original_root.is_symlink():
            raise RuntimeError(f"skill source root cannot be a symlink: {original_root}")
        root = original_root.resolve()
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(f"skill source root is not a real directory: {root}")
        for skill_dir in sorted(root.iterdir()):
            if skill_dir.is_symlink():
                raise RuntimeError(f"skill source cannot be a symlink: {skill_dir}")
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
                entries.append((scope, skill_dir.name, skill_dir))
    return entries


def _load_manifest(project: Path) -> dict | None:
    path = Path(project) / ".siesta" / MANIFEST_NAME
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("skill version manifest is not a regular file")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("skill version manifest is unreadable") from exc
    if (not isinstance(manifest, dict)
            or manifest.get("version") != SNAPSHOT_VERSION
            or not isinstance(manifest.get("skills"), list)):
        raise RuntimeError("skill version manifest has an unsupported format")
    return manifest


def _snapshot_path(project: Path, scope: str, name: str) -> Path:
    return Path(project) / ".siesta" / "skills" / scope / name


def _verify_manifest(project: Path, manifest: dict) -> None:
    snapshot_root = Path(project) / ".siesta" / "skills"
    if snapshot_root.is_symlink():
        raise RuntimeError("pinned skill snapshot root cannot be a symlink")
    seen = set()
    for item in manifest["skills"]:
        name = item.get("name") if isinstance(item, dict) else None
        if (not isinstance(item, dict) or item.get("scope") not in ("factory", "adapted")
                or not isinstance(name, str)
                or not _SAFE_SKILL_NAME.fullmatch(name)):
            raise RuntimeError("skill version manifest contains an invalid entry")
        key = (item["scope"], item["name"])
        if key in seen:
            raise RuntimeError("skill version manifest contains a duplicate entry")
        seen.add(key)
        scope_root = snapshot_root / item["scope"]
        if scope_root.is_symlink():
            raise RuntimeError("pinned skill scope cannot be a symlink")
        snapshot = _snapshot_path(project, *key)
        if snapshot.is_symlink() or not snapshot.is_dir():
            raise RuntimeError(f"pinned skill snapshot is missing: {key[0]}/{key[1]}")
        digest, files = _tree_hash(snapshot)
        if digest != item.get("sha256") or files != item.get("files"):
            raise RuntimeError(f"pinned skill snapshot changed: {key[0]}/{key[1]}")


def pin_project(project: Path, *, roots: dict[str, Path] | None = None) -> dict:
    """Create a project's first skill snapshot, or verify its existing pin.

    Existing pins are authoritative on resume. The current source tree is never
    copied over them, even when factory skill files have changed since the run.
    """
    project = Path(project)
    evidence = _safe_storage(project)
    manifest = _load_manifest(project)
    if manifest is not None:
        _verify_manifest(project, manifest)
        return manifest

    snapshot_root = evidence / "skills"
    if snapshot_root.exists():
        if snapshot_root.is_symlink() or any(snapshot_root.iterdir()):
            raise RuntimeError("skill snapshots exist without their version manifest")
    roots = source_roots() if roots is None else roots
    entries = _inventory(roots)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".skills-stage-", dir=evidence))
    records = []
    try:
        for scope, name, source in entries:
            _, source_files = _tree_hash(source)
            staged = staging / scope / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, staged, symlinks=False)
            digest, copied_files = _tree_hash(staged)
            if source_files != copied_files:
                raise RuntimeError(f"skill source changed while pinning: {scope}/{name}")
            records.append({"scope": scope, "name": name, "sha256": digest,
                            "files": copied_files})

        if snapshot_root.exists() and not snapshot_root.is_symlink():
            shutil.rmtree(snapshot_root)
        os.replace(staging, snapshot_root)
        manifest = {"version": SNAPSHOT_VERSION, "skills": records}
        manifest_path = evidence / MANIFEST_NAME
        temp_manifest = evidence / f".{MANIFEST_NAME}.tmp"
        temp_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
        os.replace(temp_manifest, manifest_path)
        _verify_manifest(project, manifest)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _scope_for(path: Path, roots: dict[str, Path]) -> tuple[str, str] | None:
    candidate_lexical = Path(os.path.abspath(path))
    candidate = Path(path).resolve()
    if candidate != candidate_lexical:
        for scope in ("factory", "adapted"):
            root_lexical = Path(os.path.abspath(roots[scope]))
            try:
                candidate_lexical.relative_to(root_lexical)
            except ValueError:
                continue
            raise RuntimeError(f"skill source paths cannot traverse symlinks: {path}")
    for scope in ("factory", "adapted"):
        root = Path(roots[scope]).resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) != 1:
            raise RuntimeError(f"skills must name one registered skill directory: {path}")
        return scope, relative.name
    return None


def resolve_paths(project: Path, skills, *, roots: dict[str, Path] | None = None) -> tuple[Path, ...]:
    """Map recognized source skills to the immutable per-project snapshots."""
    if not skills:
        return ()
    roots = source_roots() if roots is None else roots
    manifest = pin_project(project, roots=roots)
    indexed = {(item["scope"], item["name"]): item for item in manifest["skills"]}
    resolved = []
    for skill in skills:
        original = Path(skill)
        key = _scope_for(original, roots)
        if key is None:
            resolved.append(original)
            continue
        if key not in indexed:
            raise RuntimeError(f"skill was added after this run was pinned: {key[0]}/{key[1]}")
        resolved.append(_snapshot_path(project, *key))
    return tuple(resolved)


def pinned_skill(project: Path, name: str, *, scope: str = "factory",
                 roots: dict[str, Path] | None = None) -> str | None:
    """Return pinned skill text, or None if it did not exist at run start."""
    manifest = pin_project(project, roots=roots)
    if not any(item["scope"] == scope and item["name"] == name
               for item in manifest["skills"]):
        return None
    return (_snapshot_path(project, scope, name) / "SKILL.md").read_text()
