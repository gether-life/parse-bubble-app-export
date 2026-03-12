from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from parser.follow_up import generate_gap_report, write_gap_files
from parser.normalizer import normalize_export


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class GapAuditTests(unittest.TestCase):
    def test_gap_report_flags_unknown_sections_and_missing_refs(self):
        raw = _load_fixture("export_dict_shape.json")
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        categories = {g.category for g in gaps}
        self.assertIn("unknown_section", categories)
        self.assertIn("missing_reference", categories)

    def test_gap_report_flags_external_contract_unknown(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        categories = {g.category for g in gaps}
        self.assertIn("external_contract_unknown", categories)

    def test_gap_report_treats_nested_element_ids_as_resolved(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Example",
                    "elements": {"el-key": {"id": "el-1", "type": "Input"}},
                    "workflows": [{"id": "wf-1", "name": "Click", "element_id": "el-1"}],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        missing_refs = [g for g in gaps if g.category == "missing_reference"]
        self.assertEqual(missing_refs, [])

    def test_gap_report_ignores_btype_id_type_tokens(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Example",
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
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        missing_refs = [g for g in gaps if g.category == "missing_reference"]
        self.assertEqual(missing_refs, [])

    def test_gap_report_still_flags_missing_element_id_as_blocker(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Example",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Missing Element",
                            "actions": [{"properties": {"element_id": "missing-el"}}],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.category == "missing_reference")
        self.assertEqual(gap.severity, "blocker")

    def test_write_gap_files_outputs_folderized_artifacts(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            writes = write_gap_files(gaps, output_dir, dry_run=False)

            self.assertTrue((output_dir / "follow_up" / "by_severity").exists())
            self.assertTrue((output_dir / "follow_up" / "by_severity").exists())
            self.assertTrue((output_dir / "follow_up" / "by_category").exists())
            self.assertFalse((output_dir / "follow_up.json").exists())
            self.assertFalse((output_dir / "follow_up.md").exists())

            # Data integrity: verify category files exist
            path = output_dir / "follow_up" / "by_category" / "api_connector_issue.json"
            self.assertFalse(path.exists())

    def test_gap_report_treats_reusable_nested_element_ids_as_resolved(self):
        raw = {
            "reusable_elements": [
                {
                    "id": "re-1",
                    "name": "Reusable A",
                    "elements": {"el-key": {"id": "el-1", "type": "Input"}},
                    "workflows": [{"id": "wf-1", "name": "Do It", "element_id": "el-1"}],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        missing_refs = [g for g in gaps if g.category == "missing_reference"]
        self.assertEqual(missing_refs, [])

    def test_gap_report_can_ignore_specific_gap_ids(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Page",
                    "workflows": [{"id": "wf-1", "name": "Click", "element_id": "missing-el"}],
                }
            ]
        }
        normalized = normalize_export(raw)
        all_gaps = generate_gap_report(normalized)
        ignored_ids = {g.id for g in all_gaps if g.category == "missing_reference"}
        self.assertTrue(ignored_ids)

        filtered_gaps = generate_gap_report(normalized, ignored_gap_ids=ignored_ids)
        filtered_ids = {g.id for g in filtered_gaps}
        self.assertTrue(ignored_ids.isdisjoint(filtered_ids))

    def test_gap_report_includes_context_for_workflow_gap(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.where_found == "pages[0].workflows[0]")
        self.assertEqual(gap.entity_type, "workflow")
        self.assertEqual(gap.entity_source_id, "wf-signup")
        self.assertEqual(gap.entity_name, "Signup Submit")
        self.assertEqual(gap.parent_entity_type, "page")
        self.assertEqual(gap.parent_entity_source_id, "page-home")
        self.assertEqual(gap.parent_entity_name, "Home")

    def test_gap_report_resolves_context_for_nested_where_found_path(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Main",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Nested Ref",
                            "actions": [{"properties": {"element_id": "missing-el"}}],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(
            g
            for g in gaps
            if g.where_found == "pages[0].workflows[0].actions[0].properties.element_id"
        )
        self.assertEqual(gap.entity_type, "workflow")
        self.assertEqual(gap.entity_source_id, "wf-1")
        self.assertEqual(gap.entity_name, "Nested Ref")
        self.assertEqual(gap.parent_entity_type, "page")
        self.assertEqual(gap.parent_entity_source_id, "page-1")
        self.assertEqual(gap.parent_entity_name, "Main")

    def test_gap_report_includes_context_for_page_level_gap(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "api_endpoint": "https://example.com/page-contract",
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.where_found == "pages[0]")
        self.assertEqual(gap.entity_type, "page")
        self.assertEqual(gap.entity_source_id, "page-1")
        self.assertEqual(gap.entity_name, "Landing")
        self.assertIsNone(gap.parent_entity_type)
        self.assertIsNone(gap.parent_entity_source_id)
        self.assertIsNone(gap.parent_entity_name)

    def test_gap_report_does_not_flag_external_contract_when_complete(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "API Call",
                            "actions": [
                                {
                                    "id": "act-1",
                                    "properties": {
                                        "endpoint": "https://example.com/hook",
                                        "method": "POST",
                                        "payload": {"id": "123"},
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

        categories = {g.category for g in gaps}
        self.assertNotIn("external_contract_unknown", categories)

    def test_gap_report_enriches_external_contract_unknown_details(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "API Call",
                            "actions": [
                                {
                                    "id": "act-1",
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

        gap = next(
            g
            for g in gaps
            if g.category == "external_contract_unknown" and g.where_found == "pages[0].workflows[0]"
        )
        self.assertEqual(gap.severity, "high")
        self.assertEqual(gap.contract_missing_parts, ["method", "payload_or_schema"])
        self.assertIn("actions[0].properties.endpoint", gap.contract_endpoint_paths or [])
        self.assertEqual(gap.contract_endpoint_examples, ["https://example.com/hook"])
        self.assertEqual(gap.contract_method_paths, [])
        self.assertEqual(gap.contract_payload_paths, [])

    def test_gap_report_includes_api_connector_friendly_name(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "API Call",
                            "actions": [
                                {
                                    "id": "act-1",
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
                                    "properties": {"endpoint": "https://api.stripe.com/v1/billing_portal/sessions"},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.category == "external_contract_unknown")
        self.assertEqual(gap.severity, "low")
        self.assertEqual(gap.api_connector_keys, ["apiconnector2-bUDQE0.bUDWo"])
        self.assertEqual(gap.api_collection_ids, ["bUDQE0"])
        self.assertEqual(gap.api_call_ids, ["bUDWo"])
        self.assertEqual(gap.api_friendly_names, ["Stripe - Create Customer Portal Session"])

    def test_external_contract_unknown_mailto_simple_link_low_severity(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Link clicked",
                            "actions": [
                                {
                                    "id": "act-1",
                                    "properties": {"url": "mailto:support@example.com"},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        external = [g for g in gaps if g.category == "external_contract_unknown"]
        self.assertGreaterEqual(len(external), 1)
        low_with_ui_rebuild = [
            g for g in external
            if g.severity == "low" and "UI rebuild" in g.recommended_action and "no API contract" in g.recommended_action
        ]
        self.assertGreaterEqual(len(low_with_ui_rebuild), 1)
        mailto_gap = next(
            (g for g in external if g.contract_endpoint_examples and "mailto:" in (g.contract_endpoint_examples[0] or "")),
            None,
        )
        self.assertIsNotNone(mailto_gap)
        self.assertEqual(mailto_gap.severity, "low")

    def test_gap_report_matches_swagger_operation_when_possible(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "API Call",
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
        swagger_contract = {
            "openapi": "3.0.0",
            "paths": {
                "/v1/billing_portal/sessions": {
                    "post": {
                        "operationId": "createBillingPortalSession",
                    }
                }
            },
        }
        normalized = normalize_export(raw, supplemental_inputs={"swagger_contract": swagger_contract})
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.category == "external_contract_unknown")
        self.assertEqual(gap.severity, "low")
        self.assertEqual(gap.swagger_operation_ids, ["createBillingPortalSession"])
        self.assertEqual(gap.swagger_operation_methods, ["POST"])
        self.assertEqual(gap.swagger_operation_paths, ["/v1/billing_portal/sessions"])

    def test_gap_report_matches_swagger_operation_from_api_name_when_endpoint_is_non_api_url(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "API Call",
                            "actions": [
                                {
                                    "id": "act-1",
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
                                    "properties": {
                                        "endpoint": "https://www.gether.life/terms",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        swagger_contract = {
            "openapi": "3.0.0",
            "paths": {
                "/v1/billing_portal/sessions": {
                    "post": {
                        "operationId": "createBillingPortalSession",
                    }
                }
            },
        }
        normalized = normalize_export(raw, supplemental_inputs={"swagger_contract": swagger_contract})
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.category == "external_contract_unknown")
        self.assertEqual(gap.swagger_operation_ids, ["createBillingPortalSession"])
        self.assertEqual(gap.swagger_operation_methods, ["POST"])
        self.assertEqual(gap.swagger_operation_paths, ["/v1/billing_portal/sessions"])

    def test_gap_id_hash_input_is_stable_with_context_enrichment(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Landing",
                    "api_endpoint": "https://example.com/page-contract",
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        gap = next(g for g in gaps if g.where_found == "pages[0]")
        stable = f"{gap.category}|{gap.where_found}|{gap.evidence}"
        expected_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12]
        self.assertEqual(gap.id, expected_id)

    def test_plugin_black_box_gaps_grouped_by_value_within_entity(self):
        # Use backend_workflow so only one entity contains the plugin refs; name must not contain "plugin".
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "Sync Job",
                    "actions": [
                        {"properties": {"plugin_id": "my-custom-plugin"}},
                        {"properties": {"widget": "my-custom-plugin"}},
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        plugin_gaps = [g for g in gaps if g.category == "plugin_black_box"]
        self.assertEqual(len(plugin_gaps), 1)
        self.assertIn("2 occurrences", plugin_gaps[0].evidence)
        self.assertIn("my-custom-plugin", plugin_gaps[0].evidence)

    def test_plugin_black_box_distinct_values_yield_separate_gaps(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "WF",
                    "actions": [
                        {"properties": {"plugin_id": "plugin-a"}},
                        {"properties": {"plugin_id": "plugin-b"}},
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        gaps = generate_gap_report(normalized)

        plugin_gaps = [g for g in gaps if g.category == "plugin_black_box"]
        self.assertEqual(len(plugin_gaps), 2)
        values = {g.evidence for g in plugin_gaps}
        self.assertTrue(any("plugin-a" in v for v in values))
        self.assertTrue(any("plugin-b" in v for v in values))


if __name__ == "__main__":
    unittest.main()

