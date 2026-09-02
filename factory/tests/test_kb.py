import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pipeline.kb import Graph


class GraphNodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.graph = Graph(Path(self.tmp.name) / "nested" / "graph.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeds_missing_graph_and_creates_parent_dirs(self):
        self.assertTrue(self.graph.path.exists())
        self.assertEqual(json.loads(self.graph.path.read_text()), {"nodes": [], "edges": []})

    def test_node_returns_id_and_persists_fields(self):
        node_id = self.graph.node("decision", "Used argparse", "Zero dependencies")
        self.assertRegex(node_id, r"^n\d+_\d+$")
        stored = json.loads(self.graph.path.read_text())["nodes"][0]
        self.assertEqual(stored["id"], node_id)
        self.assertEqual(stored["type"], "decision")
        self.assertEqual(stored["summary"], "Used argparse")
        self.assertEqual(stored["detail"], "Zero dependencies")
        self.assertRegex(stored["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_no_temp_file_left_behind(self):
        self.graph.node("decision", "s")
        leftovers = [p for p in Path(self.tmp.name).rglob("*.tmp")]
        self.assertEqual(leftovers, [])

    def test_invalid_type_rejected_when_schema_present(self):
        Path(self.graph.path.parent, "schema.json").write_text(
            json.dumps({"node_types": {"decision": {}, "blocker": {}}}))
        with self.assertRaises(ValueError):
            self.graph.node("not-a-type", "s")

    def test_any_type_allowed_without_schema(self):
        node_id = self.graph.node("anything-goes", "s")
        self.assertTrue(node_id)

    def test_edge_persists_from_to_type(self):
        a = self.graph.node("decision", "a")
        b = self.graph.node("decision", "b")
        self.graph.edge(a, b, "applied_to")
        (edge,) = json.loads(self.graph.path.read_text())["edges"]
        self.assertEqual((edge["from"], edge["to"], edge["type"]), (a, b, "applied_to"))
        self.assertIn("created_at", edge)


class GraphReads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.graph = Graph(Path(self.tmp.name) / "graph.json")
        self.a = self.graph.node("decision", "first", "d1")
        self.b = self.graph.node("blocker", "second", "d2")

    def tearDown(self):
        self.tmp.cleanup()

    def test_query_returns_all_nodes_by_default(self):
        self.assertEqual(len(self.graph.query()), 2)

    def test_query_filters_by_type(self):
        (found,) = self.graph.query(type_="blocker")
        self.assertEqual(found["id"], self.b)

    def test_query_summary_only_projects_id_type_summary(self):
        (found,) = self.graph.query(type_="decision", summary_only=True)
        self.assertEqual(list(found), ["id", "type", "summary"])

    def test_get_returns_node_or_none(self):
        self.assertEqual(self.graph.get(self.a)["summary"], "first")
        self.assertIsNone(self.graph.get("missing"))

    def test_compact_is_json_string_of_summaries(self):
        decoded = json.loads(self.graph.compact())
        self.assertEqual(len(decoded), 2)
        self.assertEqual(set(decoded[0]), {"id", "type", "summary"})


class CliShim(unittest.TestCase):
    """`python3 -m pipeline.kb` keeps the agent-facing skill docs truthful."""

    def run_shim(self, *args):
        factory = Path(__file__).resolve().parent.parent
        env = {**os.environ, "PYTHONPATH": str(factory)}
        return subprocess.run(
            [sys.executable, "-m", "pipeline.kb", *args],
            capture_output=True, text=True, env=env, check=True)

    def test_append_node_then_query_summary_only(self):
        with tempfile.TemporaryDirectory() as d:
            graph = Path(d) / "g.json"
            out = self.run_shim("append-node", str(graph), "decision", "hello", "detail").stdout
            self.assertRegex(out.strip(), r"^n\d+_\d+$")
            listing = json.loads(
                self.run_shim("query", str(graph), "--summary-only").stdout)
            self.assertEqual(listing[0]["summary"], "hello")


if __name__ == "__main__":
    unittest.main()