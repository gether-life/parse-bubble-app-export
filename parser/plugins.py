from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .models import Entity, NormalizedExport
from .path_utils import to_output_relative_path
from .normalizer import extract_page_workflows, extract_reusable_workflows

# Exclude API Connector actions (they are in api_inventory).
API_CONNECTOR_TYPE_RE = re.compile(r"^apiconnector2-([A-Za-z0-9]+)\.([A-Za-z0-9]+)$")


def collect_plugin_action_types_from_workflows(
    workflows: list[Entity],
) -> list[dict[str, Any]]:
    """Return plugin action types used in the given workflows (excludes API Connector), with occurrence count."""
    counts: dict[str, dict[str, Any]] = {}
    for workflow in workflows:
        actions = workflow.raw.get("actions")
        for _action_index, action in _coerce_actions(actions):
            action_type = action.get("type")
            if not isinstance(action_type, str) or not action_type.strip():
                continue
            if API_CONNECTOR_TYPE_RE.match(action_type):
                continue
            key = action_type
            if key not in counts:
                action_name = action.get("name")
                if isinstance(action_name, str) and action_name.strip():
                    action_name = action_name.strip()
                else:
                    action_name = None
                counts[key] = {
                    "action_type": action_type,
                    "action_name": action_name,
                    "occurrence_count": 0,
                }
            counts[key]["occurrence_count"] += 1
    return sorted(counts.values(), key=lambda x: x["action_type"])


def build_plugin_inventory(normalized: NormalizedExport) -> dict[str, Any]:
    occurrences: list[dict[str, Any]] = []

    for page in normalized.pages:
        for workflow in extract_page_workflows(page):
            occurrences.extend(
                _extract_action_types_from_workflow(
                    workflow=workflow,
                    parent_entity=page,
                    source_kind="page_workflow",
                )
            )

    for reusable in normalized.reusables:
        for workflow in extract_reusable_workflows(reusable):
            occurrences.extend(
                _extract_action_types_from_workflow(
                    workflow=workflow,
                    parent_entity=reusable,
                    source_kind="reusable_workflow",
                )
            )

    for workflow in normalized.workflows:
        occurrences.extend(
            _extract_action_types_from_workflow(
                workflow=workflow,
                parent_entity=None,
                source_kind="backend_workflow",
            )
        )

    occurrences = sorted(occurrences, key=lambda item: (item["action_type"], item["workflow_source_path"], item["action_index"]))
    by_action_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occ in occurrences:
        by_action_type[occ["action_type"]].append(occ)

    for key in list(by_action_type.keys()):
        by_action_type[key] = sorted(by_action_type[key], key=lambda item: (item["workflow_source_path"], item["action_index"]))

    summary = _build_summary(occurrences)
    return {
        "summary": summary,
        "action_types": occurrences,
        "by_action_type": dict(sorted(by_action_type.items(), key=lambda item: item[0])),
    }


def _extract_action_types_from_workflow(
    workflow: Entity,
    parent_entity: Entity | None,
    source_kind: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    actions = workflow.raw.get("actions")
    action_items = _coerce_actions(actions)

    for action_index, action in action_items:
        action_type = action.get("type")
        if not isinstance(action_type, str) or not action_type.strip():
            continue
        if API_CONNECTOR_TYPE_RE.match(action_type):
            continue

        action_name = action.get("name")
        if isinstance(action_name, str) and action_name.strip():
            action_name = action_name.strip()
        else:
            action_name = None

        out.append(
            {
                "action_type": action_type,
                "source_kind": source_kind,
                "workflow_name": workflow.source_name,
                "workflow_source_id": workflow.source_id,
                "workflow_source_path": workflow.source_path,
                "workflow_output_path": _workflow_output_path(workflow, parent_entity, source_kind),
                "parent_entity_type": parent_entity.entity_type if parent_entity else None,
                "parent_entity_name": parent_entity.source_name if parent_entity else None,
                "parent_entity_source_id": parent_entity.source_id if parent_entity else None,
                "action_index": action_index,
                "action_id": action.get("id"),
                "action_name": action_name,
            }
        )
    return out


def _coerce_actions(actions: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(actions, list):
        out = [(str(idx), item) for idx, item in enumerate(actions) if isinstance(item, dict)]
        return sorted(out, key=lambda item: _sort_key(item[0]))
    if isinstance(actions, dict):
        out = [(str(key), value) for key, value in actions.items() if isinstance(value, dict)]
        return sorted(out, key=lambda item: _sort_key(item[0]))
    return []


def _workflow_output_path(workflow: Entity, parent_entity: Entity | None, source_kind: str) -> str:
    workflow_filename = f"{_file_stem(workflow.source_name, workflow.source_id)}.json"
    if source_kind == "backend_workflow":
        return f"workflows/{workflow_filename}"
    if source_kind == "page_workflow" and parent_entity is not None:
        page_slug = _file_stem(parent_entity.source_name, parent_entity.source_id)
        return f"pages/{page_slug}/workflows/{workflow_filename}"
    if source_kind == "reusable_workflow" and parent_entity is not None:
        reusable_slug = _file_stem(parent_entity.source_name, parent_entity.source_id)
        return f"reusables/{reusable_slug}/workflows/{workflow_filename}"
    return ""


def _file_stem(name: str, stable_value: str) -> str:
    slug = _slugify(name)
    digest = hashlib.sha1(stable_value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def _sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _build_summary(occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = Counter(occ.get("source_kind") for occ in occurrences)
    unique_types = len(set(occ["action_type"] for occ in occurrences))
    return {
        "total_occurrences": len(occurrences),
        "total_action_types": unique_types,
        "by_source_kind": dict(sorted(by_source.items())),
    }


def write_plugin_inventory_files(
    normalized: NormalizedExport, output_dir: Path, dry_run: bool = False
) -> list[dict[str, Any]]:
    inventory = build_plugin_inventory(normalized)
    root = output_dir / "plugins"
    action_types_path = root / "action_types.json"

    writes: list[dict[str, Any]] = []
    _write_json(action_types_path, inventory["action_types"], writes, dry_run, output_dir, source_name="plugin_inventory_action_types")

    for action_type_key, type_occurrences in inventory["by_action_type"].items():
        slug = _slugify(action_type_key)
        path = root / "by_action_type" / f"{slug}.json"
        _write_json(path, type_occurrences, writes, dry_run, output_dir, source_name=f"plugin_inventory_by_action_type_{slug}")

    return writes


def _write_json(
    path: Path,
    payload: Any,
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
    source_name: str,
) -> None:
    writes.append(
        {
            "path": to_output_relative_path(path, output_dir),
            "bytes": len(json.dumps(payload, ensure_ascii=False)),
            "entity_type": "plugin_inventory",
            "source_id": "",
            "source_name": source_name,
            "source_path": "root",
        }
    )
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")



