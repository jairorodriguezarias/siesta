"""Knowledge-graph store — a JSON file of {nodes, edges}.

Kept byte-compatible with the graphs the bash kb-manager.sh produced
(id shape, field names, atomic tmp+mv writes, optional schema check).
The __main__ shim keeps the model-facing skill docs' command examples true.
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EMPTY = {"nodes": [], "edges": []}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


class Graph:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps(EMPTY))
        self.data = json.loads(self.path.read_text())

    def node(self, type_: str, summary: str, detail: str = "") -> str:
        schema = self.path.parent / "schema.json"
        if schema.exists():
            valid = json.loads(schema.read_text()).get("node_types", {})
            if type_ not in valid:
                raise ValueError(f"Invalid node type '{type_}'")
        node = {
            "id": f"n{int(time.time())}_{random.randint(0, 999999)}",
            "type": type_,
            "summary": summary,
            "detail": detail,
            "created_at": _now(),
        }
        self.data["nodes"].append(node)
        _save(self.path, self.data)
        return node["id"]

    def edge(self, frm: str, to: str, kind: str) -> str:
        self.data["edges"].append(
            {"from": frm, "to": to, "type": kind, "created_at": _now()})
        _save(self.path, self.data)
        return f"Edge created: {frm} -> {to} ({kind})"

    def query(self, type_: str | None = None,
              summary_only: bool = False) -> list[dict]:
        nodes = [n for n in self.data["nodes"] if type_ is None or n["type"] == type_]
        if summary_only:
            nodes = [{k: n[k] for k in ("id", "type", "summary")} for n in nodes]
        return nodes

    def get(self, node_id: str) -> dict | None:
        return next((n for n in self.data["nodes"] if n["id"] == node_id), None)

    def compact(self, type_: str | None = None) -> str:
        return json.dumps(self.query(type_=type_, summary_only=True))


def _main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.stderr.write(
            "Usage: kb.py <query|append-node|append-edge|get-node|list-all|"
            "init-project> <graph.json> [args]\n")
        raise SystemExit(1)
    cmd, path = argv[1], Path(argv[2])
    g = Graph(path)
    if cmd == "query":
        type_ = argv[argv.index("--type") + 1] if "--type" in argv else None
        print(json.dumps(g.query(type_=type_, summary_only="--summary-only" in argv),
                         separators=(",", ":")))  # jq -c style compact
    elif cmd == "append-node":
        try:
            print(g.node(argv[3], argv[4], argv[5] if len(argv) > 5 else ""))
        except ValueError as e:
            print(e, file=sys.stderr)
            raise SystemExit(1)
    elif cmd == "append-edge":
        print(g.edge(argv[3], argv[4], argv[5]))
    elif cmd == "get-node":
        node = g.get(argv[3])
        print(json.dumps(node, indent=2) if node else "", end="")
    elif cmd == "list-all":
        print(json.dumps(g.query(summary_only=True), separators=(",", ":")))
    elif cmd == "init-project":
        path.write_text(json.dumps(EMPTY))
        print(f"KB initialized at {path}")


if __name__ == "__main__":
    _main(sys.argv)