from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parser.loader import discover_input_file, load_export_bundle


class LoaderTests(unittest.TestCase):
    def test_discover_input_file_ignores_swagger_sidecar(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "export.bubble").write_text("{}", encoding="utf-8")
            (root / "swagger.json").write_text("{}", encoding="utf-8")

            source = discover_input_file(root)
            self.assertEqual(source.name, "export.bubble")

    def test_load_export_bundle_includes_swagger_contract(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "export.bubble").write_text(json.dumps({"pages": []}), encoding="utf-8")
            swagger = {
                "openapi": "3.0.0",
                "paths": {
                    "/v1/billing_portal/sessions": {
                        "post": {"operationId": "createBillingPortalSession"}
                    }
                },
            }
            (root / "swagger.json").write_text(json.dumps(swagger), encoding="utf-8")

            data, supplemental = load_export_bundle(root)
            self.assertEqual(data["pages"], [])
            self.assertEqual(supplemental["swagger_contract"]["openapi"], "3.0.0")
            self.assertTrue(any(path.endswith("swagger.json") for path in supplemental["loaded_files"]))


if __name__ == "__main__":
    unittest.main()
