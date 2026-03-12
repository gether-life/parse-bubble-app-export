from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .apis import build_api_inventory
from .models import GapItem, NormalizedExport
from .plugins import build_plugin_inventory


def build_manifest(
    normalized: NormalizedExport,
    writes: list[dict[str, Any]],
    gaps: list[GapItem],
) -> dict[str, Any]:
    severity_counts = Counter(g.severity for g in gaps)
    category_counts = Counter(g.category for g in gaps)
    swagger_summary = _swagger_summary(normalized.swagger_contract)
    api_summary = _api_manifest_summary(normalized)
    plugin_summary = _plugin_manifest_summary(normalized)
    agent_summary = _agent_manifest_summary(writes)

    return {
        "output_schema_version": "2.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_summary": {
            "top_level_keys": normalized.app_meta.get("top_level_keys", []),
            "unknown_sections": normalized.unknown_sections,
            "section_shape_warnings": normalized.section_shape_warnings,
            "supplemental_input_files": normalized.supplemental_inputs.get("loaded_files", []),
            "swagger_loaded": swagger_summary["loaded"],
            "swagger_path_count": swagger_summary["path_count"],
            "swagger_operation_count": swagger_summary["operation_count"],
        },
        "counts": {
            "pages": len(normalized.pages),
            "data_types": len(normalized.data_types),
            "workflows": len(normalized.workflows),
            "reusables": len(normalized.reusables),
            "privacy_rules": len(normalized.privacy_rules),
            "data_options": len(normalized.data_options),
            "styles": len(normalized.styles),
            "output_files": len(writes),
            "gaps_total": len(gaps),
            "gaps_by_severity": dict(severity_counts),
            "gaps_by_category": dict(category_counts),
            "unresolved_reference_count": category_counts.get("missing_reference", 0),
            "api_calls_total": api_summary["total_calls"],
            "api_unique_groups": api_summary["unique_api_groups"],
            "api_unique_providers": api_summary["unique_providers"],
            "plugin_action_types_total": plugin_summary["total_action_types"],
            "plugin_occurrences_total": plugin_summary["total_occurrences"],
            "agent_helper_files_total": agent_summary["total_files"],
        },
        "api_inventory_summary": api_summary,
        "plugin_inventory_summary": plugin_summary,
        "agent_index_summary": agent_summary,
        "files": writes,
    }


def manifest_path(output_dir: Path) -> Path:
    return output_dir / "system" / "manifest.json"


def _swagger_summary(swagger_contract: dict[str, Any] | None) -> dict[str, int | bool]:
    if not isinstance(swagger_contract, dict):
        return {"loaded": False, "path_count": 0, "operation_count": 0}

    paths = swagger_contract.get("paths")
    if not isinstance(paths, dict):
        return {"loaded": True, "path_count": 0, "operation_count": 0}

    method_names = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    operation_count = 0
    for methods in paths.values():
        if not isinstance(methods, dict):
            continue
        for method_name, operation in methods.items():
            if method_name.lower() in method_names and isinstance(operation, dict):
                operation_count += 1
    return {"loaded": True, "path_count": len(paths), "operation_count": operation_count}


def _api_manifest_summary(normalized: NormalizedExport) -> dict[str, Any]:
    full_summary = build_api_inventory(normalized)["summary"]
    by_api = full_summary.get("by_api", {})
    by_provider = full_summary.get("by_provider", {})
    return {
        "total_calls": full_summary.get("total_calls", 0),
        "unique_api_groups": len(by_api) if isinstance(by_api, dict) else 0,
        "unique_providers": len(by_provider) if isinstance(by_provider, dict) else 0,
        "by_source_kind": full_summary.get("by_source_kind", {}),
        "by_method": full_summary.get("by_method", {}),
        "contract_completeness": full_summary.get("contract_completeness", {}),
    }


def _plugin_manifest_summary(normalized: NormalizedExport) -> dict[str, Any]:
    full_summary = build_plugin_inventory(normalized)["summary"]
    return {
        "total_action_types": full_summary.get("total_action_types", 0),
        "total_occurrences": full_summary.get("total_occurrences", 0),
        "by_source_kind": full_summary.get("by_source_kind", {}),
    }


def _agent_manifest_summary(writes: list[dict[str, Any]]) -> dict[str, Any]:
    paths: dict[str, str] = {}
    for record in writes:
        if record.get("entity_type") != "agent_index":
            continue
        source_name = record.get("source_name")
        path = record.get("path")
        if not isinstance(source_name, str) or not isinstance(path, str):
            continue
        paths[source_name] = path
    return {
        "total_files": len(paths),
        "paths": dict(sorted(paths.items())),
    }

