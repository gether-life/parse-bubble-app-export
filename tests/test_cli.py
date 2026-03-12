from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from parser.cli import run
from parser.follow_up import generate_gap_report
from parser.normalizer import normalize_export


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class CliTests(unittest.TestCase):
    def test_run_overwrites_existing_output_directory(self):
        fixture = _load_fixture("export_list_shape.json")
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")
            stale_file = output_dir / "stale.txt"
            stale_file.write_text("old data", encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=False, dry_run=False)
            exit_code = run(args)

            self.assertEqual(exit_code, 0)
            self.assertFalse(stale_file.exists())
            self.assertTrue((output_dir / "system" / "manifest.json").exists())
            manifest = json.loads((output_dir / "system" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("output_schema_version", manifest)
            first_entry = manifest["files"][0]
            self.assertIn("entity_type", first_entry)
            self.assertIn("source_id", first_entry)
            self.assertIn("source_name", first_entry)
            self.assertIn("source_path", first_entry)
            self.assertTrue(any(item["entity_type"] == "gap_report" for item in manifest["files"]))
            self.assertTrue(any(item["entity_type"] == "apis" for item in manifest["files"]))
            self.assertTrue((output_dir / "apis" / "calls.json").exists())
            self.assertTrue((output_dir / "plugins" / "action_types.json").exists())
            self.assertTrue((output_dir / "README.md").exists())
            self.assertTrue((output_dir / "app_counts.md").exists())
            self.assertTrue((output_dir / "app_overview.md").exists())
            self.assertTrue((output_dir / "system" / "entity_map.json").exists())
            self.assertTrue((output_dir / "system" / "api_contracts.json").exists())
            self.assertTrue((output_dir / "system" / "workflow_map.json").exists())
            self.assertIn("api_inventory_summary", manifest)
            self.assertIn("plugin_inventory_summary", manifest)
            counts = manifest["counts"]
            self.assertIn("api_calls_total", counts)
            self.assertIn("api_unique_groups", counts)
            self.assertIn("api_unique_providers", counts)
            self.assertIn("plugin_action_types_total", counts)
            self.assertIn("plugin_occurrences_total", counts)
            self.assertIn("agent_helper_files_total", counts)
            self.assertIn("api_unique_groups", counts)
            self.assertIn("api_unique_providers", counts)
            self.assertIn("agent_helper_files_total", counts)
            api_summary = manifest["api_inventory_summary"]
            self.assertIn("total_calls", api_summary)
            self.assertIn("by_source_kind", api_summary)
            self.assertIn("contract_completeness", api_summary)
            self.assertIn("agent_index_summary", manifest)
            self.assertGreaterEqual(manifest["agent_index_summary"]["total_files"], 5)

    def test_dry_run_does_not_delete_existing_output_directory(self):
        fixture = _load_fixture("export_list_shape.json")
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")
            stale_file = output_dir / "stale.txt"
            stale_file.write_text("old data", encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=False, dry_run=True)
            exit_code = run(args)

            self.assertEqual(exit_code, 0)
            self.assertTrue(stale_file.exists())
            self.assertFalse((output_dir / "manifest.json").exists())

    def test_strict_mode_exits_nonzero_for_blocker_gaps(self):
        fixture = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [{"id": "wf-1", "name": "Submit", "element_id": "missing-element-id"}],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=True, dry_run=True)
            exit_code = run(args)

        self.assertEqual(exit_code, 2)

    def test_strict_mode_does_not_fail_for_btype_id_token(self):
        fixture = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Type Token",
                            "actions": [{"properties": {"btype_id": "custom.families"}}],
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=True, dry_run=True)
            exit_code = run(args)

        self.assertEqual(exit_code, 0)

    def test_run_writes_external_contract_detail_fields(self):
        fixture = {
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
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
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
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=False, dry_run=False)
            exit_code = run(args)

            self.assertEqual(exit_code, 0)
            report_path = output_dir / "follow_up" / "by_category" / "external_contract_unknown.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            gap = next(item for item in report if item["where_found"] == "pages[0].workflows[0]")
            self.assertEqual(gap["contract_missing_parts"], ["method", "payload_or_schema"])
            self.assertIn("actions[0].properties.endpoint", gap["contract_endpoint_paths"])
            self.assertEqual(gap["contract_endpoint_examples"], ["https://example.com/hook"])
            self.assertEqual(gap["api_friendly_names"], ["Stripe - Create Customer Portal Session"])
            self.assertEqual(gap["api_connector_keys"], ["apiconnector2-bUDQE0.bUDWo"])

    def test_run_loads_swagger_sidecar_from_input_directory(self):
        fixture = {
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
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
                                    "properties": {
                                        "endpoint": "https://api.stripe.com/v1/billing_portal/sessions",
                                        "method": "POST",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        swagger = {
            "openapi": "3.0.0",
            "paths": {
                "/v1/billing_portal/sessions": {
                    "post": {
                        "operationId": "createBillingPortalSession",
                    }
                }
            },
        }
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")
            (input_dir / "swagger.json").write_text(json.dumps(swagger), encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=output_dir, strict=False, dry_run=False)
            exit_code = run(args)

            self.assertEqual(exit_code, 0)
            manifest = json.loads((output_dir / "system" / "manifest.json").read_text(encoding="utf-8"))
            input_summary = manifest["input_summary"]
            self.assertTrue(input_summary["swagger_loaded"])
            self.assertEqual(input_summary["swagger_path_count"], 1)
            self.assertEqual(input_summary["swagger_operation_count"], 1)
            self.assertIn("api_inventory_summary", manifest)
            self.assertIn("api_calls_total", manifest["counts"])
            self.assertIn("agent_index_summary", manifest)
            self.assertIn("agent_helper_files_total", manifest["counts"])

            report_path = output_dir / "follow_up" / "by_category" / "external_contract_unknown.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            gap = next(item for item in report if item["where_found"] == "pages[0].workflows[0]")
            self.assertEqual(gap["swagger_operation_ids"], ["createBillingPortalSession"])

            # Verify swagger.json was copied to output
            output_swagger = output_dir / "system" / "swagger.json"
            self.assertTrue(output_swagger.exists())
            self.assertEqual(json.loads(output_swagger.read_text(encoding="utf-8")), swagger)

    def test_run_rejects_unsafe_output_directory(self):
        fixture = _load_fixture("export_list_shape.json")
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")

            args = argparse.Namespace(input=input_dir, output=Path("."), strict=False, dry_run=False)
            with self.assertRaises(ValueError):
                run(args)

    def test_run_can_ignore_gap_ids_from_file(self):
        fixture = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [{"id": "wf-1", "name": "Submit", "element_id": "missing-element-id"}],
                }
            ]
        }
        gaps = generate_gap_report(normalize_export(fixture))
        ignored_ids = [g.id for g in gaps if g.category == "missing_reference"]
        self.assertTrue(ignored_ids)

        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            input_dir = root / "input"
            output_dir = root / "output"
            ignore_file = root / "ignored_gap_ids.txt"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            (input_dir / "export.bubble").write_text(json.dumps(fixture), encoding="utf-8")
            ignore_file.write_text("\n".join(ignored_ids), encoding="utf-8")

            args = argparse.Namespace(
                input=input_dir,
                output=output_dir,
                strict=True,
                dry_run=True,
                ignore_gaps_file=ignore_file,
            )
            exit_code = run(args)

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
