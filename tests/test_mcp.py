"""Scope tests plus an actual stdio MCP integration test; no paid model calls."""

import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from library_agents.mcp_server import AuditSnapshot
from library_agents.storage import read_json, write_json


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_json(self.root / "catalog.json", {"run_id": "test", "source_roots": [], "items": [
            {"id": "a", "year": "2019", "name": "a.txt", "path": "/private/a.txt",
             "document": {"units": [{"label": "text", "text": "x" * 5000}]}},
            {"id": "b", "year": "2024", "name": "b.txt"}]})
        write_json(self.root / "duplicates.json", {"exact": [{"members": ["a", "b"]}],
                   "decoded_pixels": [], "same_text": [], "similar_photos": [], "export_repeats": []})
        write_json(self.root / "topics.json", {"groups": [{"members": ["a", "b"]}]})

    def test_year_scope(self):
        view = AuditSnapshot(self.root, "2019", True)
        self.assertEqual(view.inventory()["total"], 1)
        self.assertNotIn("path", view.inventory()["items"][0])
        self.assertEqual(view.evidence("exact")["total"], 0)
        with self.assertRaises(ValueError):
            view.document("b")

    def test_global_cross_year(self):
        view = AuditSnapshot(self.root)
        self.assertEqual(view.evidence("exact")["total"], 1)
        self.assertEqual(view.evidence("topics")["total"], 1)

    def test_disclosure_gate_and_bounds(self):
        with self.assertRaises(ValueError):
            AuditSnapshot(self.root).document("a")
        unit = AuditSnapshot(self.root, include_text=True).document("a")["items"][0]
        self.assertEqual(len(unit["text"]), 4000)
        self.assertTrue(unit["mcp_text_truncated"])
        for offset, limit in [(-1, 10), (0, 0), (0, 51)]:
            with self.assertRaises(ValueError):
                AuditSnapshot(self.root).inventory(offset, limit)
        with self.assertRaises(ValueError):
            AuditSnapshot(self.root).evidence("../../etc/passwd")

    def test_pagination(self):
        view = AuditSnapshot(self.root)
        self.assertEqual(view.inventory(0, 1)["next_offset"], 1)
        self.assertIsNone(view.inventory(1, 1)["next_offset"])

    @unittest.skipUnless(importlib.util.find_spec("agents"), "Install agents extra")
    def test_agent_graph_offline_marks_missing_delegation_incomplete(self):
        from library_agents.agent_review import review
        args = SimpleNamespace(run=self.root, output=self.root / "review", model="offline-test",
                               allow_model_disclosure=True, include_text=False, max_model_calls=10)

        async def fake_run(manager, *positional, **kwargs):
            self.assertEqual(len(manager.tools), 6)
            self.assertEqual(manager.mcp_servers, [])
            self.assertTrue(kwargs["run_config"].tracing_disabled)
            return SimpleNamespace(final_output="Offline wiring test, no model inference")

        with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test-not-a-real-key"}), \
                patch("agents.Runner.run", side_effect=fake_run):
            asyncio.run(review(args))
        state = read_json(args.output / "status.json")
        self.assertEqual(state["state"], "incomplete")
        self.assertEqual(len(state["missing_specialists"]), 6)
        self.assertEqual(state["model_calls"], 0)

    @unittest.skipUnless(importlib.util.find_spec("agents"), "Install agents extra")
    def test_review_requires_disclosure_consent(self):
        from library_agents.agent_review import review
        with self.assertRaisesRegex(ValueError, "allow-model-disclosure"):
            asyncio.run(review(SimpleNamespace(allow_model_disclosure=False)))

    @unittest.skipUnless(importlib.util.find_spec("agents"), "Install agents extra")
    def test_real_stdio_protocol_and_denied_text(self):
        from agents.mcp import MCPServerStdio
        from library_agents.agent_review import server_params

        async def run():
            async with MCPServerStdio(params=server_params(self.root, "2019"),
                                      client_session_timeout_seconds=30) as server:
                names = {tool.name for tool in await server.list_tools()}
                self.assertEqual(names, {"audit_overview", "list_inventory", "list_evidence", "read_document"})
                inventory = await server.call_tool("list_inventory", {})
                self.assertFalse(inventory.is_error)
                denied = await server.call_tool("read_document", {"file_id": "a"})
                self.assertTrue(denied.is_error)
                unknown = await server.call_tool("delete_file", {"file_id": "a"})
                self.assertTrue(unknown.is_error)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
