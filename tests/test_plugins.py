from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser.normalizer import normalize_export
from parser.plugins import build_plugin_inventory, write_plugin_inventory_files


class PluginInventoryTests(unittest.TestCase):
    def test_build_plugin_inventory_returns_summary_action_types_and_by_action_type(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "sync",
                    "actions": [
                        {"id": "a1", "type": "DeleteListOfThings", "name": "Delete items"},
                        {"id": "a2", "type": "ScheduleAPIEvent", "name": "Schedule"},
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        inventory = build_plugin_inventory(normalized)

        self.assertIn("summary", inventory)
        self.assertIn("action_types", inventory)
        self.assertIn("by_action_type", inventory)
        summary = inventory["summary"]
        self.assertEqual(summary["total_occurrences"], 2)
        self.assertEqual(summary["total_action_types"], 2)
        self.assertIn("by_source_kind", summary)
        self.assertEqual(len(inventory["action_types"]), 2)
        self.assertEqual(set(inventory["by_action_type"].keys()), {"DeleteListOfThings", "ScheduleAPIEvent"})

    def test_build_plugin_inventory_excludes_api_connector_actions(self):
        raw = {
            "pages": [
                {
                    "id": "p1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Submit",
                            "actions": [
                                {"id": "a1", "type": "apiconnector2-bX.y", "name": "API Call"},
                                {"id": "a2", "type": "ShowAlert", "name": "Alert"},
                            ],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        inventory = build_plugin_inventory(normalized)

        action_types = inventory["action_types"]
        self.assertEqual(len(action_types), 1)
        self.assertEqual(action_types[0]["action_type"], "ShowAlert")
        self.assertNotIn("apiconnector2-bX.y", inventory["by_action_type"])

    def test_write_plugin_inventory_files_creates_expected_structure(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "job",
                    "actions": [
                        {"id": "a1", "type": "Empty", "name": "Step 1"},
                        {"id": "a2", "type": "Message", "name": "Step 2"},
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            writes = write_plugin_inventory_files(normalized, output_dir, dry_run=False)
            root = output_dir / "plugins"

            self.assertTrue((root / "action_types.json").exists())
            self.assertTrue((root / "by_action_type").exists())

            action_types = json.loads((root / "action_types.json").read_text(encoding="utf-8"))
            self.assertEqual(len(action_types), 2)

            self.assertTrue(any(item["path"].endswith("plugins/action_types.json") for item in writes))
            self.assertTrue(all(item.get("entity_type") == "plugin_inventory" for item in writes if "plugins" in item.get("path", "")))

            self.assertTrue((root / "by_action_type" / "empty.json").exists())
            self.assertTrue((root / "by_action_type" / "message.json").exists())

    def test_build_plugin_inventory_is_deterministic(self):
        raw = {
            "pages": [
                {
                    "id": "p1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "WF",
                            "actions": [
                                {"id": "a2", "type": "Message", "name": "B"},
                                {"id": "a1", "type": "Empty", "name": "A"},
                            ],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        first = build_plugin_inventory(normalized)
        second = build_plugin_inventory(normalized)
        self.assertEqual(first, second)
