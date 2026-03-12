from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import GapItem, NormalizedExport
from .path_utils import to_output_relative_path
from .normalizer import extract_page_workflows, extract_reusable_workflows
from .semantic import generate_workflow_summary

_ARTIFACT_ORDER = [
    "README.md",
    "app_counts.md",
    "app_overview.md",
    "system/entity_map.json",
    "system/api_contracts.json",
    "system/workflow_map.json",
]


def build_agent_index_payloads(
    normalized: NormalizedExport,
    writes: list[dict[str, Any]],
    gaps: list[GapItem],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    workflow_rows = _collect_workflows(normalized)
    entity_map = {
        "pages": _entity_rows(normalized.pages),
        "data_types": _entity_rows(normalized.data_types),
        "workflows": _entity_rows(normalized.workflows),
        "reusables": _entity_rows(normalized.reusables),
        "privacy_rules": _entity_rows(normalized.privacy_rules),
        "workflows": workflow_rows,
    }
    workflow_map = {
        row["lookup_key"]: {
            "workflow_name": row["workflow_name"],
            "workflow_source_id": row["workflow_source_id"],
            "workflow_source_path": row["workflow_source_path"],
            "workflow_output_path": row["workflow_output_path"],
            "parent_entity_type": row["parent_entity_type"],
            "parent_entity_name": row["parent_entity_name"],
            "parent_entity_source_id": row["parent_entity_source_id"],
        }
        for row in workflow_rows
    }

    api_contract_items = _api_contract_todo_items(gaps)
    manifest_counts = manifest.get("counts", {})

    return {
        "README.md": _root_readme(),
        "app_counts.md": _root_summary(manifest, gaps),
        "app_overview.md": _app_overview(normalized),
        "system/entity_map.json": entity_map,
        "system/api_contracts.json": {
            "total": len(api_contract_items),
            "items": api_contract_items,
        },
        "system/workflow_map.json": workflow_map,
    }


def write_agent_index_files(
    payloads: dict[str, Any], output_dir: Path, dry_run: bool = False
) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    for filename in _ARTIFACT_ORDER:
        payload = payloads.get(filename)
        if payload is None:
            continue
        path = output_dir / filename
        source_name = f"agent_index_{filename.replace('.', '_').replace('/', '_')}"
        if isinstance(payload, str):
            writes.append(_write_record(path, len(payload.encode("utf-8")), source_name, output_dir))
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
            continue
        writes.append(_write_record(path, len(json.dumps(payload, ensure_ascii=False)), source_name, output_dir))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return writes


def _entity_rows(entities: list[Any]) -> list[dict[str, str]]:
    rows = [
        {
            "entity_type": entity.entity_type,
            "source_id": entity.source_id,
            "source_name": entity.source_name,
            "source_path": entity.source_path,
        }
        for entity in entities
    ]
    return sorted(rows, key=lambda item: (item["source_path"], item["source_id"]))


def _collect_workflows(normalized: NormalizedExport) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for page in normalized.pages:
        page_slug = _file_stem(page.source_name, page.source_id)
        for workflow in extract_page_workflows(page):
            rows.append(
                {
                    "lookup_key": f"page:{page.source_id}:{workflow.source_id}",
                    "workflow_name": workflow.source_name,
                    "workflow_source_id": workflow.source_id,
                    "workflow_source_path": workflow.source_path,
                    "workflow_output_path": (
                        f"pages/{page_slug}/workflows/"
                        f"{_file_stem(workflow.source_name, workflow.source_id)}.json"
                    ),
                    "parent_entity_type": "page",
                    "parent_entity_name": page.source_name,
                    "parent_entity_source_id": page.source_id,
                }
            )
    for reusable in normalized.reusables:
        reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
        for workflow in extract_reusable_workflows(reusable):
            rows.append(
                {
                    "lookup_key": f"reusable:{reusable.source_id}:{workflow.source_id}",
                    "workflow_name": workflow.source_name,
                    "workflow_source_id": workflow.source_id,
                    "workflow_source_path": workflow.source_path,
                    "workflow_output_path": (
                        f"reusables/{reusable_slug}/workflows/"
                        f"{_file_stem(workflow.source_name, workflow.source_id)}.json"
                    ),
                    "parent_entity_type": "reusable_element",
                    "parent_entity_name": reusable.source_name,
                    "parent_entity_source_id": reusable.source_id,
                }
            )
    for workflow in normalized.workflows:
        rows.append(
            {
                "lookup_key": f"backend:{workflow.source_id}",
                "workflow_name": workflow.source_name,
                "workflow_source_id": workflow.source_id,
                "workflow_source_path": workflow.source_path,
                "workflow_output_path": (
                    f"workflows/{_file_stem(workflow.source_name, workflow.source_id)}.json"
                ),
                "parent_entity_type": "",
                "parent_entity_name": "",
                "parent_entity_source_id": "",
            }
        )
    return sorted(rows, key=lambda item: item["lookup_key"])


def _api_contract_todo_items(gaps: list[GapItem]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for gap in gaps:
        if gap.category != "external_contract_unknown":
            continue
        if gap.entity_type not in {"workflow", "backend_workflow"}:
            continue
        selected.append(
            {
                "gap_id": gap.id,
                "category": gap.category,
                "severity": gap.severity,
                "where_found": gap.where_found,
                "entity_type": gap.entity_type,
                "entity_name": gap.entity_name,
                "parent_entity_type": gap.parent_entity_type,
                "parent_entity_name": gap.parent_entity_name,
                "endpoint_examples": gap.contract_endpoint_examples or [],
                "method_values": gap.contract_method_values or [],
                "payload_paths": gap.contract_payload_paths or [],
                "missing_parts": gap.contract_missing_parts or [],
                "recommended_action": gap.recommended_action,
                "swagger_operation_ids": gap.swagger_operation_ids or [],
            }
        )
    return sorted(selected, key=lambda item: item["gap_id"])


def _top_gap_paths(writes: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for record in writes:
        if record.get("entity_type") != "gap_report":
            continue
        path_value = record.get("path")
        if not isinstance(path_value, str):
            continue
        normalized = _as_output_path(path_value)
        if "/by_severity/" in normalized or "/by_category/" in normalized:
            paths.append(normalized)
    return sorted(paths)[:8]


def _as_output_path(path_value: str) -> str:
    """Return path relative to output root (strip /output/ prefix if present for backward compat)."""
    marker = "/output/"
    idx = path_value.rfind(marker)
    if idx >= 0:
        return path_value[idx + len(marker) :]
    return path_value


def _root_readme() -> str:
    return (
        "# Bubble Export Parser Output\n\n"
        "This directory contains the normalized, AI-ready structural output of the parsed Bubble app.\n"
        "The monolithic export has been broken down to improve searchability and context-caching capabilities for agents.\n\n"
        "## Output Directory Structure\n\n"
        "### Overview & Guidance\n"
        "- `README.md`: the file you're reading now.\n"
        "- `app_overview.md`: Semantic, narrative summary of how the core logic executes per page.\n"
        "- `app_counts.md`: Statistical counts for the scale of the app (number of endpoints, gaps, elements, etc.).\n\n"
        "### Project Data\n"
        "- `pages/`: Individual pages containing their DOM elements, reusables, and workflows.\n"
        "- `reusables/`: Reusable Elements that act as components, complete with their workflows.\n"
        "- `workflows/`: Standalone Backend Workflows and API Workflows.\n"
        "- `data_types/`: Defines the schemas for all database Tables/Custom Types.\n"
        "- `data_privacy/`: Security rules for the data_types.\n"
        "- `styles/` & `data_options/`: Central application styles and Option Sets.\n"
        "- `plugins/` & `apis/`: Custom action types and third-party API configurations.\n"
        "- `follow_up/`: Highlighted missing references, unknown node shapes, or implementation blind spots.\n\n"
        "### System Indexes\n"
        "- `system/`: Contains technical metadata, ID maps, and manifest files.\n\n"
        "## Using with AI Agents (e.g. Google Deepmind Antigravity)\n"
        "To assist an AI coding agent with understanding the Bubble app, command your agent sequentially to:\n"
        "1. Read `app_overview.md` to get the conceptual breakdown and behavior of Pages and Reusables.\n"
        "2. Read `app_counts.md` to understand the scale parameters.\n"
        "3. Inspect `system/workflow_map.json` and `system/api_contracts.json` to lookup paths for specific behaviors you want the agent to migrate or rewrite.\n"
        "4. Start diving straight into the specific JSONs in `pages/` or `workflows/`."
    )


def _write_record(path: Path, size: int, source_name: str, output_dir: Path) -> dict[str, Any]:
    return {
        "path": to_output_relative_path(path, output_dir),
        "bytes": size,
        "entity_type": "agent_index",
        "source_id": "",
        "source_name": source_name,
        "source_path": "root",
    }


def _file_stem(name: str, stable_value: str) -> str:
    slug = _slugify(name)
    digest = hashlib.sha1(stable_value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def _root_summary(manifest: dict[str, Any], gaps: list[GapItem]) -> str:
    counts = manifest.get("counts", {})
    api_summary = manifest.get("api_inventory_summary", {})
    plugin_summary = manifest.get("plugin_inventory_summary", {})

    lines = [
        "# Export Summary",
        "",
        "## General Counts",
        f"- **Pages**: {counts.get('pages', 0)}",
        f"- **Data Types**: {counts.get('data_types', 0)}",
        f"- **Reusable Elements**: {counts.get('reusables', 0)}\n"
        f"- **Backend Workflows**: {counts.get('workflows', 0)}\n",
        f"- **Privacy Rules**: {counts.get('privacy_rules', 0)}",
        "",
        "## External APIs",
        f"- **Total API Calls**: {counts.get('api_calls_total', 0)}",
        f"- **Unique API Groups**: {counts.get('api_unique_groups', 0)}",
        f"- **Unique Providers**: {counts.get('api_unique_providers', 0)}",
        "",
        "## Plugins & Custom Actions",
        f"- **Total Occurrences**: {counts.get('plugin_occurrences_total', 0)}",
        f"- **Unique Action Types**: {counts.get('plugin_action_types_total', 0)}",
        "",
        "## Migration Gaps",
        f"- **Total Gaps**: {counts.get('gaps_total', 0)}",
        f"- **Blocker Gaps**: {counts.get('gaps_by_severity', {}).get('blocker', 0)}",
        f"- **High Severity Gaps**: {counts.get('gaps_by_severity', {}).get('high', 0)}",
        f"- **Unresolved References**: {counts.get('unresolved_reference_count', 0)}",
        "",
        "For detailed lists of plugins, APIs, and follow-up gaps, check the `plugins/`, `apis/`, and `follow_up/` directories.",
    ]
    return "\n".join(lines)

def _app_overview(normalized: NormalizedExport) -> str:
    summary = "# Application Summary\n\nThis document provides a conceptual overview of the app's components based on the raw Bubble export data.\n\n"
    
    summary += "## Pages\n\n"
    for page in normalized.pages:
        page_slug = _file_stem(page.source_name, page.source_id)
        workflows = extract_page_workflows(page)
        
        for wf in workflows:
            wf_summary = generate_workflow_summary([wf])
            wf_slug = _file_stem(wf.source_name, wf.source_id)
            summary += f"# Workflows for {page.source_name} (See pages/{page_slug}/workflows/{wf_slug}.json)\n\n"
            summary += f"{wf_summary}\n"

    summary += "## Reusable Elements\n\n"
    for reusable in normalized.reusables:
        reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
        workflows = extract_reusable_workflows(reusable)

        for wf in workflows:
            wf_summary = generate_workflow_summary([wf])
            wf_slug = _file_stem(wf.source_name, wf.source_id)
            summary += f"# Workflows for {reusable.source_name} (See reusables/{reusable_slug}/workflows/{wf_slug}.json)\n\n"
            summary += f"{wf_summary}\n"

    return summary
