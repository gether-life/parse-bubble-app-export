from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import Entity, NormalizedExport


SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "pages": ("pages",),
    "data_types": ("data_types", "types", "thing_types", "user_types"),
    "workflows": ("backend_workflows", "api_workflows", "api_endpoints", "api"),
    "reusables": ("reusable_elements", "reusables", "reusable_views", "element_definitions"),
    "privacy_rules": ("privacy_rules", "privacy"),
    "data_options": ("data_options", "option_sets"),
    "styles": ("styles",),
}


def normalize_export(
    raw: dict[str, Any], supplemental_inputs: dict[str, Any] | None = None
) -> NormalizedExport:
    used_keys: set[str] = set()
    section_shape_warnings: list[str] = []

    # Apply structural improvement: convert numeric dictionaries to native arrays
    raw = _convert_numeric_dicts_to_lists(raw)

    normalized = NormalizedExport(
        raw=raw,
        app_meta={"top_level_keys": sorted(raw.keys())},
        supplemental_inputs=supplemental_inputs or {},
        swagger_contract=(supplemental_inputs or {}).get("swagger_contract"),
    )

    normalized.pages = _normalize_section(
        raw, "page", SECTION_ALIASES["pages"], used_keys, section_shape_warnings
    )
    normalized.data_types = _normalize_section(
        raw, "data_type", SECTION_ALIASES["data_types"], used_keys, section_shape_warnings
    )
    normalized.workflows = _normalize_section(
        raw,
        "workflow",
        SECTION_ALIASES["workflows"],
        used_keys,
        section_shape_warnings,
    )
    normalized.reusables = _normalize_section(
        raw,
        "reusable_element",
        SECTION_ALIASES["reusables"],
        used_keys,
        section_shape_warnings,
    )
    normalized.privacy_rules = _normalize_section(
        raw, "privacy_rule", SECTION_ALIASES["privacy_rules"], used_keys, section_shape_warnings
    )
    if not normalized.privacy_rules and isinstance(raw.get("user_types"), dict):
        used_keys.add("user_types")
        normalized.privacy_rules = _privacy_from_user_types(raw["user_types"])

    normalized.data_options = _normalize_section(
        raw, "data_option", SECTION_ALIASES["data_options"], used_keys, section_shape_warnings
    )
    normalized.styles = _normalize_section(
        raw, "style", SECTION_ALIASES["styles"], used_keys, section_shape_warnings
    )

    normalized.unknown_sections = sorted(k for k in raw.keys() if k not in used_keys)
    normalized.section_shape_warnings = section_shape_warnings
    return normalized


def extract_page_elements(page: Entity) -> list[dict[str, Any]]:
    elements = page.raw.get("elements", [])
    return [item for _, item in _coerce_container_to_items(elements)]


def extract_page_workflows(page: Entity) -> list[Entity]:
    workflows = page.raw.get("workflows")
    if workflows is None:
        workflows = page.raw.get("events", [])
    return _extract_workflow_entities(page.source_path, workflows)


def extract_reusable_elements(reusable: Entity) -> list[dict[str, Any]]:
    elements = reusable.raw.get("elements", [])
    return [item for _, item in _coerce_container_to_items(elements)]


def extract_reusable_workflows(reusable: Entity) -> list[Entity]:
    workflows = reusable.raw.get("workflows")
    if workflows is None:
        workflows = reusable.raw.get("events", [])
    return _extract_workflow_entities(reusable.source_path, workflows)


def _extract_workflow_entities(parent_source_path: str, workflows: Any) -> list[Entity]:
    source_path = f"{parent_source_path}.workflows"
    out: list[Entity] = []
    for idx, (_, item) in enumerate(_coerce_container_to_items(workflows)):
        workflow_source_path = f"{source_path}[{idx}]"
        out.append(
            Entity(
                entity_type="workflow",
                source_path=workflow_source_path,
                source_id=_extract_id(item, source_path=workflow_source_path),
                source_name=_extract_name(item, "workflow", idx),
                raw=item,
            )
        )
    return out


def _normalize_section(
    raw: dict[str, Any],
    entity_type: str,
    aliases: tuple[str, ...],
    used_keys: set[str],
    section_shape_warnings: list[str],
) -> list[Entity]:
    key, payload = _pick_section(raw, aliases)
    if key is None:
        return []

    used_keys.add(key)
    items = _coerce_container_to_items(payload)
    if not isinstance(payload, (list, dict)):
        section_shape_warnings.append(
            f"Section '{key}' has unsupported type '{type(payload).__name__}' and was skipped."
        )
        return []

    entities: list[Entity] = []
    for idx, (container_key, item) in enumerate(items):
        source_path = f"{key}[{idx}]"
        source_id = _extract_id(item, container_key=container_key, source_path=source_path)
        entities.append(
            Entity(
                entity_type=entity_type,
                source_path=source_path,
                source_id=source_id,
                source_name=_extract_name(item, entity_type, idx, container_key),
                raw=item,
            )
        )
    return entities


def _pick_section(
    raw: dict[str, Any], aliases: tuple[str, ...]
) -> tuple[str | None, Any]:
    for key in aliases:
        if key in raw:
            return key, raw[key]
    return None, None


def _coerce_container_to_items(container: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(container, list):
        return [(str(i), x) for i, x in enumerate(container) if isinstance(x, dict)]
    if isinstance(container, dict):
        return [(str(k), v) for k, v in container.items() if isinstance(v, dict)]
    return []


def _extract_id(
    item: dict[str, Any],
    container_key: str | None = None,
    source_path: str = "",
) -> str:
    for key in ("id", "_id", "uid", "unique_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    if container_key and container_key.strip():
        return container_key
    canonical_payload = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    fallback_seed = f"{source_path}|{canonical_payload}"
    return f"missing-{hashlib.sha1(fallback_seed.encode('utf-8')).hexdigest()[:10]}"


def _extract_name(
    item: dict[str, Any], fallback_prefix: str, idx: int, container_key: str | None = None
) -> str:
    if fallback_prefix == "workflow":
        wf_name = item.get("properties", {}).get("wf_name")
        if wf_name is not None and str(wf_name).strip():
            return str(wf_name)

    if fallback_prefix == "data_type":
        for key in ("display", "display_name", "label", "title", "name"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value)

    for key in ("name", "display_name", "default_name", "label", "title"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    if container_key and container_key.strip():
        return container_key
    if item.get("type"):
        return f"{fallback_prefix}-{item['type']}-{idx}"
    return f"{fallback_prefix}-{idx}"


def _privacy_from_user_types(user_types: dict[str, Any]) -> list[Entity]:
    entities: list[Entity] = []
    for idx, (type_name, item) in enumerate(user_types.items()):
        if not isinstance(item, dict):
            continue
        privacy = item.get("privacy_role")
        if not isinstance(privacy, dict):
            continue
        # Use same display name as data_type so privacy rules align with data_types (find one from the other)
        display_name = _extract_name(item, "data_type", idx, type_name)
        raw = {"type_name": type_name, "privacy_role": privacy}
        entities.append(
            Entity(
                entity_type="privacy_rule",
                source_path=f"user_types[{idx}].privacy_role",
                source_id=type_name,
                source_name=display_name,
                raw=raw,
            )
        )
    return entities


def _convert_numeric_dicts_to_lists(node: Any) -> Any:
    """
    Recursively detect dictionaries where all keys are sequential numeric strings 
    ('0', '1', '2'...) and convert them to native JSON arrays.
    """
    if isinstance(node, dict):
        # Is it a sequential numeric dict?
        if node and all(isinstance(k, str) and k.isdigit() for k in node.keys()):
            int_keys = sorted(int(k) for k in node.keys())
            if int_keys == list(range(len(int_keys))):
                return [_convert_numeric_dicts_to_lists(node[str(i)]) for i in range(len(int_keys))]
        
        return {k: _convert_numeric_dicts_to_lists(v) for k, v in node.items()}
        
    elif isinstance(node, list):
        return [_convert_numeric_dicts_to_lists(item) for item in node]
    
    return node


