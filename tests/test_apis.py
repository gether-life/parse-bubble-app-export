from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser.apis import build_api_inventory, write_api_inventory_files
from parser.normalizer import normalize_export


class ApiInventoryTests(unittest.TestCase):
    def test_build_api_inventory_extracts_connector_call_details(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Create Session",
                            "actions": {
                                "0": {
                                    "id": "act-1",
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
                                    "properties": {
                                        "method": "POST",
                                        "endpoint": "https://api.stripe.com/v1/billing_portal/sessions?foo=bar",
                                        "headers": {"Authorization": "Bearer sk_test"},
                                        "params": {"customer": "cus_123"},
                                        "body": {"customer": "cus_123"},
                                    },
                                }
                            },
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)

        inventory = build_api_inventory(normalized)
        calls = inventory["calls"]
        self.assertEqual(len(calls), 1)

        call = calls[0]
        self.assertEqual(call["api_name"], "Stripe - Create Customer Portal Session")
        self.assertEqual(call["api_connector_key"], "apiconnector2-bUDQE0.bUDWo")
        self.assertEqual(call["api_collection_id"], "bUDQE0")
        self.assertEqual(call["api_call_id"], "bUDWo")
        self.assertEqual(call["method_literal"], "POST")
        self.assertEqual(call["url_literal"], "https://api.stripe.com/v1/billing_portal/sessions?foo=bar")
        self.assertEqual(call["path"], "/v1/billing_portal/sessions")
        self.assertEqual(call["query_params"].get("foo"), "bar")
        self.assertEqual(call["headers_raw"], {"Authorization": "Bearer sk_test"})
        self.assertEqual(call["params_raw"], {"customer": "cus_123"})
        self.assertEqual(call["payload_raw"], {"customer": "cus_123"})
        self.assertEqual(call["source_kind"], "page_workflow")
        self.assertEqual(call["workflow_name"], "Create Session")
        self.assertEqual(call["parent_entity_name"], "Home")

    def test_build_api_inventory_matches_swagger_operation(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "Create Session",
                            "actions": {
                                "0": {
                                    "id": "act-1",
                                    "name": "Stripe - Create Customer Portal Session",
                                    "type": "apiconnector2-bUDQE0.bUDWo",
                                    "properties": {
                                        "method": "POST",
                                        "endpoint": "https://api.stripe.com/v1/billing_portal/sessions",
                                    },
                                }
                            },
                        }
                    ],
                }
            ]
        }
        swagger = {
            "openapi": "3.0.0",
            "paths": {
                "/v1/billing_portal/sessions": {
                    "post": {"operationId": "createBillingPortalSession"}
                }
            },
        }
        normalized = normalize_export(raw, supplemental_inputs={"swagger_contract": swagger})

        inventory = build_api_inventory(normalized)
        call = inventory["calls"][0]
        self.assertEqual(call["swagger_operation_ids"], ["createBillingPortalSession"])
        self.assertEqual(call["swagger_operation_methods"], ["POST"])
        self.assertEqual(call["swagger_operation_paths"], ["/v1/billing_portal/sessions"])

    def test_write_api_inventory_files_outputs_expected_structure(self):
        raw = {
            "backend_workflows": [
                {
                    "id": "bw-1",
                    "name": "sync-users",
                    "actions": {
                        "0": {
                            "id": "act-1",
                            "name": "Internal Sync",
                            "type": "apiconnector2-bSYNC.bCALL",
                            "properties": {
                                "request_url": "https://api.example.com/v1/users",
                                "http_method": "GET",
                            },
                        }
                    },
                }
            ]
        }
        normalized = normalize_export(raw)

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir)
            writes = write_api_inventory_files(normalized, output_dir, dry_run=False)
            root = output_dir / "apis"


            self.assertTrue((root / "calls.json").exists())

            self.assertTrue((root / "by_api").exists())

            calls = json.loads((root / "calls.json").read_text(encoding="utf-8"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["source_kind"], "backend_workflow")

            self.assertTrue(any(item["path"].endswith("apis/calls.json") for item in writes))

    def test_build_api_inventory_is_deterministic(self):
        raw = {
            "pages": [
                {
                    "id": "page-1",
                    "name": "Home",
                    "workflows": [
                        {
                            "id": "wf-1",
                            "name": "WF",
                            "actions": {
                                "1": {
                                    "id": "act-2",
                                    "name": "Call B",
                                    "type": "apiconnector2-bA.c2",
                                    "properties": {"endpoint": "https://api.example.com/v1/b", "method": "GET"},
                                },
                                "0": {
                                    "id": "act-1",
                                    "name": "Call A",
                                    "type": "apiconnector2-bA.c1",
                                    "properties": {"endpoint": "https://api.example.com/v1/a", "method": "GET"},
                                },
                            },
                        }
                    ],
                }
            ]
        }
        normalized = normalize_export(raw)
        first = build_api_inventory(normalized)
        second = build_api_inventory(normalized)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
