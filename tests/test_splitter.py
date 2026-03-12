from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser.normalizer import normalize_export
from parser.splitter import split_export


FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class SplitterTests(unittest.TestCase):
    def test_splitter_writes_expected_structure(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            writes = split_export(normalized, Path(tempdir), dry_run=False)

        self.assertTrue(any(item["path"].endswith("system/app_meta.json") for item in writes))
        self.assertTrue(any("data_types" in item["path"] for item in writes))
        self.assertTrue(any("workflows/" in item["path"] for item in writes))
        self.assertTrue(any("reusables/" in item["path"] for item in writes))
        self.assertTrue(any("data_privacy" in item["path"] for item in writes))
        self.assertTrue(
            any("pages" in item["path"] and item["path"].endswith("entity.json") for item in writes)
        )
        self.assertFalse(any(item["path"].endswith("/page.json") for item in writes))
        self.assertTrue(any("pages" in item["path"] and "elements/part-" in item["path"] for item in writes))
        self.assertFalse(any(item["path"].endswith("/elements.json") for item in writes))
        self.assertTrue(any("workflows" in item["path"] for item in writes))
        self.assertTrue(any(item.get("entity_type") == "app_meta" for item in writes))
        self.assertTrue(any(item.get("entity_type") == "page" for item in writes))
        self.assertTrue(any(item.get("entity_type") == "workflow" for item in writes))

    def test_splitter_filenames_are_deterministic(self):
        raw = _load_fixture("export_list_shape.json")
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp_path = Path(tempdir)
            writes_first = split_export(normalized, tmp_path / "run1", dry_run=True)
            writes_second = split_export(normalized, tmp_path / "run2", dry_run=True)

        normalized_first = sorted(Path(item["path"]).name for item in writes_first)
        normalized_second = sorted(Path(item["path"]).name for item in writes_second)
        self.assertEqual(normalized_first, normalized_second)

    def test_splitter_chunks_page_elements(self):
        many_elements = {f"e{i}": {"id": f"el-{i}", "type": "Text"} for i in range(600)}
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Huge Page",
                    "elements": many_elements,
                    "workflows": [],
                }
            ]
        }
        normalized = normalize_export(raw)
        writes = split_export(normalized, Path("/tmp/unused"), dry_run=True)

        self.assertFalse(any(item["path"].endswith("/elements.json") for item in writes))
        chunk_paths = [item["path"] for item in writes if "elements/part-" in item["path"]]
        self.assertGreaterEqual(len(chunk_paths), 2)
        self.assertTrue(all(item.get("entity_type") == "page_elements_chunk" for item in writes if item["path"] in chunk_paths))

    def test_splitter_splits_reusable_elements_like_pages(self):
        raw = {
            "reusable_elements": [
                {
                    "id": "re-1",
                    "name": "Header",
                    "elements": [{"id": "el-1", "type": "Group"}],
                    "workflows": [{"id": "wf-1", "name": "Open Menu"}],
                }
            ]
        }
        normalized = normalize_export(raw)
        writes = split_export(normalized, Path("/tmp/unused"), dry_run=True)

        self.assertTrue(
            any(
                "reusables/" in item["path"] and item["path"].endswith("entity.json")
                for item in writes
            )
        )
        self.assertTrue(
            any("reusables/" in item["path"] and "elements/part-0001.json" in item["path"] for item in writes)
        )
        self.assertTrue(
            any("reusables/" in item["path"] and "workflows/" in item["path"] for item in writes)
        )
        self.assertTrue(
            any("reusables/" in item["path"] and "workflows/" in item["path"] for item in writes)
        )

    def test_splitter_includes_current_and_legacy_names_for_data_types(self):
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

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)
            data_type_write = next(item for item in writes if "data_types" in item["path"])
            payload = json.loads((tmp / data_type_write["path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["meta"]["source_name"], "Job Message")
        self.assertEqual(payload["meta"]["display_name"], "Job Message")
        self.assertEqual(payload["meta"]["legacy_name"], "task")

    def test_splitter_adds_field_display_and_legacy_metadata_for_data_types(self):
        raw = {
            "data_types": [
                {
                    "id": "task",
                    "display": "Job",
                    "fields": {
                        "job_name_text": {"display": "Job Name", "value": "text"},
                        "created_date": {"value": "date"},
                    },
                }
            ]
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)
            data_type_write = next(item for item in writes if "data_types" in item["path"])
            payload = json.loads((tmp / data_type_write["path"]).read_text(encoding="utf-8"))

        fields = payload["data"]["fields"]
        self.assertEqual(fields["job_name_text"]["display_name"], "Job Name")
        self.assertEqual(fields["job_name_text"]["legacy_key"], "job_name_text")
        self.assertEqual(fields["created_date"]["display_name"], "created_date")
        self.assertEqual(fields["created_date"]["legacy_key"], "created_date")

    def test_splitter_backend_workflow_data_name_matches_wf_name(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bVCeT",
                    "name": "batch-job-analysis-delete",
                    "properties": {"wf_name": "batch-job-audit-delete"},
                }
            ]
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)
            workflow_write = next(item for item in writes if "workflows/" in item["path"])
            payload = json.loads((tmp / workflow_write["path"]).read_text(encoding="utf-8"))

        self.assertEqual(payload["meta"]["source_name"], "batch-job-audit-delete")
        self.assertEqual(payload["data"]["properties"]["wf_name"], "batch-job-audit-delete")
        self.assertEqual(payload["data"]["name"], "batch-job-audit-delete")

    def test_splitter_writes_reusable_elements_json_per_page(self):
        raw = {
            "pages": [
                {
                    "id": "p1",
                    "name": "Home",
                    "elements": {
                        "root": {
                            "type": "Group",
                            "id": "root",
                            "elements": {
                                "ce1": {
                                    "type": "CustomElement",
                                    "properties": {"custom_id": "re-1"},
                                }
                            },
                        }
                    },
                    "workflows": [],
                }
            ],
            "reusable_elements": [
                {"id": "re-1", "name": "Header"},
            ],
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)

        page_reusable_writes = [
            w for w in writes
            if "pages" in w["path"] and w["path"].endswith("reusables.json")
        ]
        self.assertGreaterEqual(len(page_reusable_writes), 1, "expected at least one pages/.../reusables.json write")
        rec = page_reusable_writes[0]
        self.assertEqual(rec.get("entity_type"), "page_reusable_elements")
        path = rec["path"]
        self.assertIn("pages/", path)
        self.assertTrue(path.endswith("reusables.json"))

        with tempfile.TemporaryDirectory() as tempdir2:
            tmp2 = Path(tempdir2)
            split_export(normalized, tmp2, dry_run=False)
            full_path = tmp2 / path
            self.assertTrue(full_path.exists(), f"expected file at {full_path}; listdir: {list(tmp2.rglob('*'))}")
            payload = json.loads(full_path.read_text(encoding="utf-8"))
        self.assertIn("page_slug", payload)
        self.assertIn("page_name", payload)
        self.assertIn("used_reusables", payload)
        self.assertEqual(payload["page_name"], "Home")
        self.assertEqual(len(payload["used_reusables"]), 1)
        self.assertEqual(payload["used_reusables"][0]["reusable_id"], "re-1")
        self.assertEqual(payload["used_reusables"][0]["reusable_name"], "Header")
        self.assertIn("reusables/", payload["used_reusables"][0]["reusable_path"])

    def test_splitter_writes_plugins_used_json_per_page_and_reusable(self):
        raw = {
            "pages": [
                {
                    "id": "p1",
                    "name": "Home",
                    "elements": [],
                    "workflows": [
                        {
                            "id": "w1",
                            "name": "Button clicked",
                            "actions": [
                                {"type": "resetgroup", "name": "Reset group"},
                                {"type": "alert", "name": "Show alert"},
                            ],
                        }
                    ],
                }
            ],
            "reusable_elements": [
                {
                    "id": "re-1",
                    "name": "Header",
                    "elements": [],
                    "workflows": [
                        {
                            "id": "wf1",
                            "name": "Open",
                            "actions": [{"type": "resetgroup", "name": "Reset"}],
                        }
                    ],
                }
            ],
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)

        page_plugins_writes = [
            w for w in writes
            if "pages" in w["path"] and w["path"].endswith("plugins.json")
        ]
        reusable_plugins_writes = [
            w for w in writes
            if "reusables" in w["path"] and w["path"].endswith("plugins.json")
        ]
        self.assertGreaterEqual(len(page_plugins_writes), 1)
        self.assertGreaterEqual(len(reusable_plugins_writes), 1)
        self.assertEqual(page_plugins_writes[0].get("entity_type"), "page_plugins_used")
        self.assertEqual(reusable_plugins_writes[0].get("entity_type"), "reusable_plugins_used")

        with tempfile.TemporaryDirectory() as tempdir2:
            tmp2 = Path(tempdir2)
            split_export(normalized, tmp2, dry_run=False)
            page_path = tmp2 / page_plugins_writes[0]["path"]
            self.assertTrue(page_path.exists())
            page_payload = json.loads(page_path.read_text(encoding="utf-8"))
        self.assertEqual(page_payload["page_name"], "Home")
        self.assertIn("used_plugins", page_payload)
        action_types = [p["action_type"] for p in page_payload["used_plugins"]]
        self.assertIn("resetgroup", action_types)
        self.assertIn("alert", action_types)
        self.assertEqual(page_payload["used_plugins"][0]["occurrence_count"], 1)

    def test_splitter_writes_data_types_used_json_per_page_and_reusable(self):
        raw = {
            "pages": [
                {
                    "id": "p1",
                    "name": "Home",
                    "elements": [{"type": "Group", "properties": {"thing_type": "custom.user"}}],
                    "workflows": [
                        {
                            "id": "w1",
                            "name": "Clicked",
                            "actions": [
                                {
                                    "type": "NewThing",
                                    "properties": {"thing_type": "custom.user"},
                                }
                            ],
                        }
                    ],
                }
            ],
            "reusable_elements": [
                {
                    "id": "re-1",
                    "name": "Header",
                    "elements": [],
                    "workflows": [
                        {
                            "id": "wf1",
                            "name": "Open",
                            "actions": [
                                {
                                    "type": "CreateThing",
                                    "properties": {"thing_type": "custom.families"},
                                }
                            ],
                        }
                    ],
                }
            ],
            "user_types": {
                "other": {"display": "Other"},
                "user": {"display": "User"},
                "families": {"display": "Family"},
            },
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            tmp = Path(tempdir)
            writes = split_export(normalized, tmp, dry_run=False)

            page_dt_writes = [
                w for w in writes
                if "pages" in w["path"] and w["path"].endswith("data_types.json")
            ]
            reusable_dt_writes = [
                w for w in writes
                if "reusables" in w["path"] and w["path"].endswith("data_types.json")
            ]
            self.assertGreaterEqual(len(page_dt_writes), 1)
            self.assertGreaterEqual(len(reusable_dt_writes), 1)
            self.assertEqual(page_dt_writes[0].get("entity_type"), "page_data_types_used")
            self.assertEqual(reusable_dt_writes[0].get("entity_type"), "reusable_data_types_used")

            page_path = tmp / page_dt_writes[0]["path"]
            self.assertTrue(page_path.exists(), f"Expected {page_path} to exist")
            page_payload = json.loads(page_path.read_text(encoding="utf-8"))
            self.assertEqual(page_payload["page_name"], "Home")
            self.assertIn("used_data_types", page_payload)
            # user appears in page elements and workflow
            user_entries = [e for e in page_payload["used_data_types"] if e["data_type_source_id"] == "user"]
            self.assertEqual(len(user_entries), 1)
            self.assertEqual(user_entries[0]["data_type_name"], "User")
            self.assertGreaterEqual(user_entries[0]["occurrence_count"], 1)
            self.assertIn("data_types/", user_entries[0]["data_type_path"])

            reusable_path = tmp / reusable_dt_writes[0]["path"]
            self.assertTrue(reusable_path.exists(), f"Expected {reusable_path} to exist")
            reusable_payload = json.loads(reusable_path.read_text(encoding="utf-8"))
            self.assertEqual(reusable_payload["reusable_name"], "Header")
            self.assertIn("used_data_types", reusable_payload)
            family_entries = [e for e in reusable_payload["used_data_types"] if e["data_type_source_id"] == "families"]
            self.assertEqual(len(family_entries), 1)
            self.assertEqual(family_entries[0]["data_type_name"], "Family")


if __name__ == "__main__":
    unittest.main()

