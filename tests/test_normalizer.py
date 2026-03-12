from __future__ import annotations

import json
import unittest
from pathlib import Path

from parser.normalizer import extract_page_workflows, normalize_export


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class NormalizerTests(unittest.TestCase):
    def test_normalizer_handles_list_shape(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)

        self.assertEqual(len(normalized.pages), 1)
        self.assertEqual(len(normalized.data_types), 1)
        self.assertEqual(len(normalized.workflows), 1)
        self.assertEqual(len(normalized.reusables), 1)
        self.assertEqual(len(normalized.privacy_rules), 1)
        self.assertEqual(normalized.unknown_sections, [])
        self.assertEqual(normalized.pages[0].entity_type, "page")

    def test_normalizer_handles_dict_shape_and_aliases(self):
        raw = _load_fixture("export_dict_shape.json")
        normalized = normalize_export(raw)

        self.assertEqual(len(normalized.pages), 1)
        self.assertEqual(len(normalized.data_types), 1)
        self.assertEqual(len(normalized.workflows), 1)
        self.assertEqual(len(normalized.reusables), 1)
        self.assertEqual(len(normalized.privacy_rules), 1)
        self.assertIn("new_unmapped_section", normalized.unknown_sections)

    def test_page_workflow_extraction_uses_events_fallback(self):
        raw = _load_fixture("export_dict_shape.json")
        normalized = normalize_export(raw)
        workflows = extract_page_workflows(normalized.pages[0])

        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0].source_name, "Click CTA")

    def test_workflow_missing_id_fallback_is_unique_per_source_path(self):
        raw = {
            "pages": [
                {
                    "id": "page-a",
                    "name": "A",
                    "workflows": [
                        {"name": "Same Shape"},
                        {"name": "Same Shape"},
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        workflows = extract_page_workflows(normalized.pages[0])

        self.assertEqual(len(workflows), 2)
        self.assertNotEqual(workflows[0].source_id, workflows[1].source_id)

    def test_backend_workflow_prefers_wf_name_from_properties(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "bUdmQ",
                    "properties": {"wf_name": "user-family-remove"},
                }
            ]
        }
        normalized = normalize_export(raw)

        self.assertEqual(len(normalized.workflows), 1)
        self.assertEqual(normalized.workflows[0].source_name, "user-family-remove")

    def test_data_type_prefers_display_label_as_current_name(self):
        raw = {
            "data_types": [
                {
                    "id": "task",
                    "name": "task",
                    "display": "Job Message",
                }
            ]
        }
        normalized = normalize_export(raw)

        self.assertEqual(len(normalized.data_types), 1)
        self.assertEqual(normalized.data_types[0].source_name, "Job Message")

    def test_privacy_from_user_types_uses_display_name_and_type_id_to_align_with_data_types(self):
        """Privacy rules derived from user_types should match data type display name and source_id for easy lookup."""
        raw = {
            "user_types": {
                "gmail_email": {"display": "Job", "privacy_role": {"everyone": {"display": "everyone"}}},
                "families": {"display": "Family", "privacy_role": {"everyone": {}}},
            }
        }
        normalized = normalize_export(raw)
        self.assertEqual(len(normalized.privacy_rules), 2)
        by_id = {e.source_id: e for e in normalized.privacy_rules}
        self.assertEqual(by_id["gmail_email"].source_name, "Job")
        self.assertEqual(by_id["families"].source_name, "Family")
        self.assertIn("gmail_email", by_id)
        self.assertIn("families", by_id)


if __name__ == "__main__":
    unittest.main()

