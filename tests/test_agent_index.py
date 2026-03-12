from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser.agent_index import build_agent_index_payloads, write_agent_index_files
from parser.follow_up import generate_gap_report
from parser.manifest import build_manifest
from parser.normalizer import normalize_export
from parser.splitter import split_export


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class AgentIndexTests(unittest.TestCase):
    def test_write_agent_index_files_writes_all_root_artifacts(self):
        normalized = normalize_export(_load_fixture("export_list_shape.json"))
        gaps = generate_gap_report(normalized)
        writes = split_export(normalized, Path("/tmp/unused"), dry_run=True)
        manifest = build_manifest(normalized, writes, gaps)
        payloads = build_agent_index_payloads(normalized, writes, gaps, manifest)

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            write_records = write_agent_index_files(payloads, output_dir, dry_run=False)

            expected_paths = {
                output_dir / "README.md",
                output_dir / "app_counts.md",
                output_dir / "app_overview.md",
                output_dir / "system" / "entity_map.json",
                output_dir / "system" / "api_contracts.json",
                output_dir / "system" / "workflow_map.json",
            }
            self.assertEqual(
                {output_dir / item["path"] for item in write_records}, expected_paths
            )
            for path in expected_paths:
                self.assertTrue(path.exists(), f"missing expected artifact: {path}")

    def test_build_agent_index_payloads_is_deterministic_with_stable_schema(self):
        normalized = normalize_export(_load_fixture("export_list_shape.json"))
        gaps = generate_gap_report(normalized)
        writes = split_export(normalized, Path("/tmp/unused"), dry_run=True)
        manifest = build_manifest(normalized, writes, gaps)

        first = build_agent_index_payloads(normalized, writes, gaps, manifest)
        second = build_agent_index_payloads(normalized, writes, gaps, manifest)
        self.assertEqual(first, second)
        self.assertEqual(
            sorted(first.keys()),
            sorted(
                [
                    "README.md",
                    "app_counts.md",
                    "app_overview.md",
                    "system/entity_map.json",
                    "system/api_contracts.json",
                    "system/workflow_map.json",
                ]
            ),
        )

    def test_build_agent_index_payloads_selects_external_contract_todos(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "External Call",
                            "actions": [
                                {
                                    "id": "act-1",
                                    "type": "apiconnector2-aA1.bB2",
                                    "name": "Stripe - Call",
                                    "properties": {
                                        "endpoint": "https://example.com/hook",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)
        manifest = build_manifest(normalized, [], gaps)
        payloads = build_agent_index_payloads(normalized, [], gaps, manifest)

        todos = payloads["system/api_contracts.json"]["items"]
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["category"], "external_contract_unknown")
        self.assertIn("https://example.com/hook", todos[0]["endpoint_examples"])
        self.assertEqual(todos[0]["missing_parts"], ["method", "payload_or_schema"])

    def test_entity_map_and_workflow_lookup_include_parent_metadata(self):
        normalized = normalize_export(_load_fixture("export_list_shape.json"))
        gaps = generate_gap_report(normalized)
        manifest = build_manifest(normalized, [], gaps)
        payloads = build_agent_index_payloads(normalized, [], gaps, manifest)

        entity_map = payloads["system/entity_map.json"]
        workflows = entity_map["workflows"]
        page_workflow = next(item for item in workflows if item["parent_entity_type"] == "page")
        self.assertEqual(page_workflow["parent_entity_name"], "Home")
        self.assertTrue(page_workflow["workflow_output_path"].startswith("pages/"))

        workflow_lookup = payloads["system/workflow_map.json"]
        record = next(item for item in workflow_lookup.values() if item["parent_entity_type"] == "page")
        self.assertEqual(record["parent_entity_type"], "page")
        self.assertEqual(record["parent_entity_name"], "Home")
        self.assertIn("/workflows/", record["workflow_output_path"])


if __name__ == "__main__":
    unittest.main()
