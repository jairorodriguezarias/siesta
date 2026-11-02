"""User supplied KB references are snapshotted into new projects."""
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.kb import Graph
from pipeline import references


class ReferenceTests(unittest.TestCase):
    def test_new_project_copies_global_references_once_and_uses_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            factory = root / "factory"
            global_graph = Graph(factory / "kb/global-graph.json")
            global_graph.node("reference", "Audience", "People who read on phones")
            project = root / "project"
            project_graph = Graph(project / "kb/graph.json")
            self.assertEqual(references.snapshot(project_graph, global_graph), 1)
            self.assertEqual(references.snapshot(project_graph, global_graph), 0)
            self.assertIn("People who read on phones",
                          references.context(project_graph))
            global_graph.node("reference", "Later", "Future projects only")
            self.assertNotIn("Future projects only", references.context(project_graph))

    def test_reference_input_and_context_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph(Path(directory) / "graph.json")
            with self.assertRaises(ValueError):
                references.add(graph, " ", "detail")
            with self.assertRaises(ValueError):
                references.add(graph, "Valid", "x" * 12001)
            references.add(graph, "Valid", "x" * 12000)
            context = references.context(graph)
            self.assertLessEqual(len(context), references.CONTEXT_LIMIT + 200)
            self.assertIn("truncated", context)

    def test_recent_reference_gets_prompt_space_first(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph(Path(directory) / "graph.json")
            references.add(graph, "Old", "o" * 8000)
            references.add(graph, "New", "n" * 8000)
            context = references.context(graph)
            self.assertIn('"title": "New"', context)
            self.assertNotIn('"title": "Old"', context)


if __name__ == "__main__":
    unittest.main()
