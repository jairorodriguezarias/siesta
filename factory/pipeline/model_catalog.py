"""Read-only Pi/Ollama catalog and explicit model compatibility checks."""
from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from pipeline import model_selection
from pipeline.pi import ROLE, run_pi

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_OLLAMA = "http://127.0.0.1:11434"


def _profile_path() -> Path:
    configured = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(configured) if configured else Path.home() / ".pi" / "agent"


def _profile_digest() -> str:
    path = _profile_path() / "models.json"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "builtin-only"


def _registered_models() -> tuple[set[str], str | None]:
    try:
        result = subprocess.run(["pi", "--offline", "--list-models", "ollama"],
                                capture_output=True, text=True, timeout=15,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return set(), f"Pi catalog unavailable: {type(exc).__name__}"
    if result.returncode:
        return set(), f"Pi catalog exited with status {result.returncode}"
    names = set()
    for line in result.stdout.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and columns[0] == "ollama":
            names.add(columns[1])
    return names, None


def _installed_models() -> tuple[dict[str, dict], str | None]:
    try:
        with urllib.request.urlopen(_OLLAMA + "/api/tags", timeout=5) as stream:
            response = json.load(stream)
        models = response.get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama returned no model list")
        return {row["name"]: row for row in models
                if isinstance(row, dict) and isinstance(row.get("name"), str)}, None
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {}, f"Ollama catalog unavailable: {type(exc).__name__}"


def _validations_path(factory: Path) -> Path:
    return Path(factory) / ".runtime" / "model-validations.json"


def _validations(factory: Path) -> dict:
    try:
        value = json.loads(_validations_path(factory).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_validation(factory: Path, name: str, value: dict) -> None:
    path = _validations_path(factory)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            existing = _validations(factory)
            existing[name] = value
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def catalog(factory: Path) -> dict:
    """List exact IDs from Pi, Ollama and committed role defaults."""
    registered, pi_error = _registered_models()
    installed, ollama_error = _installed_models()
    defaults = json.loads((Path(factory) / "config" / "models.json").read_text())
    configured = {route["model"] for route in defaults.values()
                  if isinstance(route, dict) and route.get("provider") == "ollama"}
    validations = _validations(factory)
    profile = _profile_digest()
    entries = []
    for name in sorted(registered | installed.keys() | configured):
        record = installed.get(name)
        if record and record.get("remote_host"):
            origin = "cloud"
        elif record:
            origin = "local"
        elif name.endswith(":cloud") or name.endswith("-cloud"):
            origin = "cloud"
        else:
            origin = "unknown"
        stored = validations.get(name, {})
        validated = bool(stored.get("compatible") and stored.get("profile") == profile
                         and name in registered and name in installed)
        entries.append({"id": name, "provider": "ollama", "origin": origin,
                        "advertised": name in registered or name in configured,
                        "installed": name in installed,
                        "pi_registered": name in registered,
                        "validated": validated,
                        "preparation": (None if name in registered and name in installed else
                                        "Register this exact ID in Pi" if name not in registered else
                                        "Install or pull this exact ID in Ollama")})
    return {"models": entries, "ollama_available": ollama_error is None,
            "pi_available": pi_error is None,
            "errors": [error for error in (pi_error, ollama_error) if error]}


def check_compatibility(factory: Path, *, model: str, provider: str = "ollama",
                        tools: bool = True) -> dict:
    """Run the selected model without falling back to another ID."""
    if (provider != "ollama" or not isinstance(model, str)
            or not _MODEL_ID.fullmatch(model) or type(tools) is not bool):
        raise ValueError("Expected an Ollama model ID and a boolean tools flag")
    entry = next((row for row in catalog(factory)["models"] if row["id"] == model), None)
    if entry is None or not entry["pi_registered"]:
        return {"model": model, "provider": provider, "status": "needs_setup",
                "reason": "The exact model is not registered in this Pi profile"}
    if not entry["installed"]:
        return {"model": model, "provider": provider, "status": "needs_setup",
                "reason": "The exact model is not installed in Ollama"}

    with tempfile.TemporaryDirectory(prefix="siesta-model-check-") as directory:
        root = Path(directory)
        selection = model_selection.normalize_selection({"phases": {
            "verification": {"model": model, "provider": provider},
            "implementation": {"model": model, "provider": provider},
        }}, role_defaults=ROLE)
        model_selection.save_project(root, selection)
        try:
            answer = run_pi("consultant", "Reply with only SIESTA_MODEL_READY.",
                            "Check selected model", cwd=root, tools="no",
                            isolated=True, phase_name="verification")
            text_ok = "SIESTA_MODEL_READY" in answer
            tool_ok = None
            if text_ok and tools:
                tool_answer = run_pi(
                    "worker", "Use the write tool to create model-tool-proof.txt "
                    "in the current directory containing exactly SIESTA_TOOL_READY. "
                    "Then report completion.", "Check selected model tools",
                    cwd=root, tools="write", isolated=True,
                    phase_name="implementation", context_kind="issue")
                proof = root / "model-tool-proof.txt"
                tool_ok = proof.is_file() and proof.read_text().strip() == "SIESTA_TOOL_READY"
                if not tool_ok and not tool_answer:
                    reason = "Model call or authentication failed during tool check"
                elif not tool_ok:
                    reason = "Model did not perform the required native write tool action"
            if not text_ok:
                reason = "Model call or authentication failed; no expected response"
            elif tool_ok is False and not reason:
                reason = "Native write tool check failed"
            else:
                reason = "Compatible with the requested checks"
        except (OSError, ValueError, RuntimeError) as exc:
            text_ok, tool_ok = False, None
            reason = f"Compatibility check failed: {type(exc).__name__}"
    compatible = text_ok and tool_ok is not False
    _save_validation(factory, model, {
        "compatible": compatible, "text": text_ok, "tools": tool_ok,
        "profile": _profile_digest(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason})
    return {"model": model, "provider": provider,
            "status": "compatible" if compatible else "incompatible",
            "text": text_ok, "tools": tool_ok, "reason": reason}
