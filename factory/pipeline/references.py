"""User references supplied before a project starts."""
import json

MAX_REFERENCES = 50
CONTEXT_LIMIT = 12000


def add(graph, summary: str, detail: str) -> str:
    if not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 160:
        raise ValueError("Reference title must be 1–160 characters")
    if not isinstance(detail, str) or not 1 <= len(detail.strip()) <= 12000:
        raise ValueError("Reference text must be 1–12000 characters")
    if "\x00" in summary + detail:
        raise ValueError("Reference contains an invalid character")
    if len(graph.query(type_="reference")) >= MAX_REFERENCES:
        raise ValueError("Reference limit reached")
    return graph.node("reference", summary.strip(), detail.strip())


def snapshot(project_graph, global_graph) -> int:
    """Copy current global references to a new project's committed KB."""
    source = global_graph.query(type_="reference")
    if len(source) > MAX_REFERENCES:
        raise ValueError("Global reference limit exceeded")
    existing = {(node["summary"], node["detail"])
                for node in project_graph.query(type_="reference")}
    copied = 0
    for node in source:
        pair = (node["summary"], node["detail"])
        if pair not in existing:
            project_graph.node("reference", *pair)
            existing.add(pair)
            copied += 1
    return copied


def context(graph) -> str:
    """Full reference text for prompts, with an explicit size limit."""
    notes = list(reversed(graph.query(type_="reference")))
    if not notes:
        return "(none)"
    included = []
    truncated = False
    for node in notes:
        item = {"title": node["summary"], "text": node["detail"]}
        candidate = json.dumps([*included, item], ensure_ascii=False)
        if len(candidate) > CONTEXT_LIMIT:
            truncated = True
            if not included:
                item["text"] = node["detail"]
                while len(json.dumps([item], ensure_ascii=False)) > CONTEXT_LIMIT:
                    item["text"] = item["text"][:len(item["text"]) // 2]
                included.append(item)
            break
        included.append(item)
    data = json.dumps(included, ensure_ascii=False)
    if truncated:
        return data + f"\n[reference context truncated; {len(notes) - len(included)} note(s) omitted]"
    return data
