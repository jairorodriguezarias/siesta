"""Bounded source collection shared by tool-free pipeline reviewers."""
from pathlib import Path

from pipeline import text
from pipeline.files import source_files


SOURCE_EXTS = {"html", "css", "js", "ts", "py", "go", "rs", "json", "md",
               "sh", "jsx", "tsx", "vue", "svelte"}
GATHER_BUDGET = 120_000


def gather(proj: Path, *, budget: int = GATHER_BUDGET,
           exclude: set[str] | None = None) -> str:
    """Collect bounded source text, optionally excluding relative paths."""
    excluded = exclude or set()
    files = [path for path in source_files(proj)
             if path.suffix.lstrip(".") in SOURCE_EXTS
             and path.relative_to(proj).as_posix() not in excluded]
    parts = []
    remaining = budget
    for index, path in enumerate(files):
        if remaining <= 0:
            parts.append(f"\n\n--- TRUNCATED: {len(files) - index} further "
                         f"source files not shown (context budget) ---")
            break
        with path.open(errors="replace") as stream:
            content = text.head(stream.read(remaining), 500)
        header = f"\n\n--- File: {path.relative_to(proj)} ---\n"
        if len(header) + len(content) > remaining:
            cut = "\n--- (file cut mid-way: context budget) ---"
            room = remaining - len(header) - len(cut)
            shown = len(files) - index
            if room > 0:
                parts.append(header + content[:room] + cut)
                shown = len(files) - index - 1
            parts.append(f"\n\n--- TRUNCATED: {shown} further source "
                         f"files not shown (context budget) ---")
            break
        parts.append(header + content)
        remaining -= len(header) + len(content)
    return "".join(parts)
