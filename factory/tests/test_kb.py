import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pipeline.kb import Graph


class SeedBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "global-graph.json"
        self.seed = self.path.with_name("global-seed.json")
        graph = Graph(self.seed)
        graph.node("principle", "Keep projects simple")

    def test_new_graph_copies_seed_without_modifying_it(self):
        original = self.seed.read_bytes()
        graph = Graph(self.path, seed=self.seed)
        self.assertEqual(graph.query("principle"), Graph(self.seed).query())
        graph.node("learning", "Private run detail")
        self.assertEqual(self.seed.read_bytes(), original)
        self.assertEqual(len(Graph(self.path).query()), 2)

    def test_existing_graph_is_preserved_even_when_empty(self):
        for populated in (False, True):
            with self.subTest(populated=populated):
                graph = Graph(self.path)
                if populated:
                    graph.node("decision", "Keep this local decision")
                original = self.path.read_bytes()
                Graph(self.path, seed=self.seed)
                self.assertEqual(self.path.read_bytes(), original)

    def test_missing_seed_creates_empty_graph(self):
        graph = Graph(self.path, seed=self.path.with_name("missing.json"))
        self.assertEqual(graph.query(), [])

    def test_invalid_seed_does_not_create_live_graph(self):
        self.seed.write_text("invalid JSON")
        with self.assertRaises(json.JSONDecodeError):
            Graph(self.path, seed=self.seed)
        self.assertFalse(self.path.exists())


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


class GraphEdges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.graph = Graph(Path(self.tmp.name) / "graph.json")
        self.a = self.graph.node("decision", "a")
        self.b = self.graph.node("decision", "b")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_schema(self, edge_types):
        Path(self.graph.path.parent, "schema.json").write_text(
            json.dumps({"node_types": {"decision": {}}, "edge_types": edge_types}))

    def test_valid_edge_created_with_schema_present(self):
        self._write_schema({"applied_to": {}})
        self.graph.edge(self.a, self.b, "applied_to")
        (edge,) = json.loads(self.graph.path.read_text())["edges"]
        self.assertEqual((edge["from"], edge["to"]), (self.a, self.b))

    def test_dangling_from_rejected(self):
        with self.assertRaises(ValueError):
            self.graph.edge("missing", self.b, "applied_to")
        self.assertEqual(json.loads(self.graph.path.read_text())["edges"], [])

    def test_dangling_to_rejected(self):
        with self.assertRaises(ValueError):
            self.graph.edge(self.a, "missing", "applied_to")
        self.assertEqual(json.loads(self.graph.path.read_text())["edges"], [])

    def test_invalid_kind_rejected_when_schema_present(self):
        self._write_schema({"applied_to": {}})
        with self.assertRaises(ValueError):
            self.graph.edge(self.a, self.b, "not-a-kind")

    def test_any_kind_allowed_without_schema(self):
        self.graph.edge(self.a, self.b, "anything-goes")
        self.assertEqual(len(json.loads(self.graph.path.read_text())["edges"]), 1)


class SharedPathInstances(unittest.TestCase):
    """round-5: __main__ and phases each held a Graph over the global KB —
    the stale instance's save wiped the fresh one's nodes (per-issue
    learnings vanished at phase 7). Every operation re-reads the file, so
    concurrent instances never lose each other's writes."""

    def test_stale_instance_write_does_not_wipe_concurrent_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "graph.json"
            first = Graph(path)
            first.node("learning", "from a previous run")
            second = Graph(path)          # loaded before first writes again
            first.node("learning", "per-issue learning")
            second.node("learning", "project-level learning")   # the wipe scenario
            stored = [n["summary"] for n in Graph(path).query("learning")]
        self.assertEqual(stored, ["from a previous run",
                                  "per-issue learning", "project-level learning"])

    def test_query_sees_nodes_written_via_another_instance(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "graph.json"
            first = Graph(path)
            second = Graph(path)
            first.node("decision", "later write")
            self.assertEqual([n["summary"] for n in second.query("decision")],
                             ["later write"])


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
