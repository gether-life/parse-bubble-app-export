from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .models import Entity, NormalizedExport
from .path_utils import to_output_relative_path
from .normalizer import (
    extract_page_elements,
    extract_page_workflows,
    extract_reusable_elements,
    extract_reusable_workflows,
)
from .plugins import collect_plugin_action_types_from_workflows
from .semantic import extract_style_system, extract_element_id_map, extract_dom_skeleton, generate_workflow_summary, inject_ast_interpretations


def _collect_custom_element_ids(elements_container: Any) -> set[str]:
    """Recursively collect custom_id from all CustomElement nodes in an element tree."""
    ids: set[str] = set()
    if not elements_container:
        return ids
    items: list[tuple[str, Any]] = []
    if isinstance(elements_container, list):
        items = [(str(i), x) for i, x in enumerate(elements_container) if isinstance(x, dict)]
    elif isinstance(elements_container, dict):
        items = [(k, v) for k, v in elements_container.items() if isinstance(v, dict)]
    for _key, node in items:
        if node.get("type") == "CustomElement":
            cid = (node.get("properties") or {}).get("custom_id")
            if cid and str(cid).strip():
                ids.add(str(cid).strip())
        ids |= _collect_custom_element_ids(node.get("elements"))
    return ids


def _collect_thing_type_refs(node: Any) -> Counter[str]:
    """Recursively collect thing_type and btype_id string values; return counts keyed by source_id (custom. prefix stripped)."""
    counts: Counter[str] = Counter()
    if node is None:
        return counts
    if isinstance(node, dict):
        for key in ("thing_type", "btype_id"):
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                raw = val.strip()
                if raw.startswith("custom."):
                    raw = raw[7:]
                if raw:
                    counts[raw] += 1
        for v in node.values():
            counts.update(_collect_thing_type_refs(v))
    elif isinstance(node, list):
        for item in node:
            counts.update(_collect_thing_type_refs(item))
    return counts

ELEMENTS_SINGLE_FILE_MAX_BYTES = 250_000
ELEMENTS_SINGLE_FILE_MAX_ITEMS = 500
ELEMENTS_CHUNK_SIZE = 250


def split_export(normalized: NormalizedExport, output_dir: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    _write_json(
        output_dir / "system" / "app_meta.json",
        normalized.app_meta,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "app_meta",
            "source_id": "",
            "source_name": "app_meta",
            "source_path": "root",
        },
    )

    # Phase 1 Semantic AI Outputs
    style_system = extract_style_system(normalized.raw)
    _write_json(
        output_dir / "system" / "style_system.json",
        style_system,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "style_system",
            "source_id": "",
            "source_name": "style_system",
            "source_path": "root",
        },
    )

    element_id_map = extract_element_id_map(normalized.raw)
    _write_json(
        output_dir / "system" / "element_id_map.json",
        element_id_map,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "element_id_map",
            "source_id": "",
            "source_name": "element_id_map",
            "source_path": "root",
        },
    )

    writes.extend(_write_entity_group(normalized.data_types, output_dir / "data_types", dry_run, output_dir))
    writes.extend(_write_entity_group(normalized.workflows, output_dir / "workflows", dry_run, output_dir))
    

    
    for reusable in normalized.reusables:
        reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
        reusable_dir = output_dir / "reusables" / reusable_slug
        reusable_payload = {"meta": _entity_meta(reusable), "data": reusable.raw}
        _write_json(
            reusable_dir / "entity.json",
            reusable_payload,
            writes,
            dry_run,
            output_dir=output_dir,
            record_meta=_entity_meta(reusable),
        )

        reusable_elements = extract_reusable_elements(reusable)
        _write_element_chunks(
            reusable_elements,
            reusable,
            reusable_dir,
            writes,
            dry_run,
            output_dir=output_dir,
            entity_type="reusable_elements_chunk",
        )
        
        # Phase 2 Semantic AI Outputs
        skeleton_payload = extract_dom_skeleton(reusable.raw.get("elements", {}))
        _write_json(
            reusable_dir / "elements.skeleton.json",
            {"skeleton": skeleton_payload},
            writes,
            dry_run,
            output_dir=output_dir,
            record_meta={
                "entity_type": "reusable_elements_skeleton",
                "source_id": reusable.source_id,
                "source_name": reusable.source_name,
                "source_path": reusable.source_path,
            },
        )

        workflows_list = extract_reusable_workflows(reusable)
        for workflow in workflows_list:
            filename = f"{_file_stem(workflow.source_name, workflow.source_id)}.json"
            payload = {"meta": _entity_meta(workflow), "data": workflow.raw}
            _write_json(
                reusable_dir / "workflows" / filename,
                payload,
                writes,
                dry_run,
                output_dir=output_dir,
                record_meta=_entity_meta(workflow),
            )
            

        _write_reusable_plugins_used(
            reusable,
            reusable_dir,
            writes,
            dry_run,
            output_dir,
        )
        _write_reusable_data_types_used(
            reusable,
            reusable_dir,
            normalized.data_types,
            writes,
            dry_run,
            output_dir,
        )
    writes.extend(_write_entity_group(normalized.privacy_rules, output_dir / "data_privacy", dry_run, output_dir))
    writes.extend(_write_entity_group(normalized.data_options, output_dir / "data_options", dry_run, output_dir))
    writes.extend(_write_entity_group(normalized.styles, output_dir / "styles", dry_run, output_dir))

    for page in normalized.pages:
        page_slug = _file_stem(page.source_name, page.source_id)
        page_dir = output_dir / "pages" / page_slug
        page_payload = {"meta": _entity_meta(page), "data": page.raw}
        _write_json(page_dir / "entity.json", page_payload, writes, dry_run, output_dir=output_dir, record_meta=_entity_meta(page))

        elements = extract_page_elements(page)
        _write_element_chunks(
            elements,
            page,
            page_dir,
            writes,
            dry_run,
            output_dir=output_dir,
            entity_type="page_elements_chunk",
        )
        
        # Phase 2 Semantic AI Outputs
        skeleton_payload = extract_dom_skeleton(page.raw.get("elements", {}))
        _write_json(
            page_dir / "elements.skeleton.json",
            {"skeleton": skeleton_payload},
            writes,
            dry_run,
            output_dir=output_dir,
            record_meta={
                "entity_type": "page_elements_skeleton",
                "source_id": page.source_id,
                "source_name": page.source_name,
                "source_path": page.source_path,
            },
        )

        workflows_list = extract_page_workflows(page)
        for workflow in workflows_list:
            filename = f"{_file_stem(workflow.source_name, workflow.source_id)}.json"
            payload = {"meta": _entity_meta(workflow), "data": workflow.raw}
            _write_json(
                page_dir / "workflows" / filename,
                payload,
                writes,
                dry_run,
                output_dir=output_dir,
                record_meta=_entity_meta(workflow),
            )
            


        _write_page_reusables(
            page,
            page_dir,
            normalized.reusables,
            writes,
            dry_run,
            output_dir,
        )
        _write_page_plugins_used(
            page,
            page_dir,
            writes,
            dry_run,
            output_dir,
        )
        _write_page_data_types_used(
            page,
            page_dir,
            normalized.data_types,
            writes,
            dry_run,
            output_dir,
        )
    return writes


def _write_page_reusables(
    page: Entity,
    page_dir: Path,
    reusables: list[Entity],
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
) -> None:
    """Write reusables.json for a page listing reusables used on that page (Bubble-style)."""
    elements_container = page.raw.get("elements")
    custom_ids = _collect_custom_element_ids(elements_container)
    reusable_by_id = {e.source_id: e for e in reusables}
    page_slug = _file_stem(page.source_name, page.source_id)
    used_reusables = []
    for cid in sorted(custom_ids):
        reusable = reusable_by_id.get(cid)
        if reusable is None:
            continue
        reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
        used_reusables.append({
            "reusable_id": reusable.source_id,
            "reusable_name": reusable.source_name,
            "reusable_path": f"reusables/{reusable_slug}",
        })
    payload = {
        "page_slug": page_slug,
        "page_name": page.source_name,
        "used_reusables": used_reusables,
    }
    _write_json(
        page_dir / "reusables.json",
        payload,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "page_reusable_elements",
            "source_id": page.source_id,
            "source_name": page.source_name,
            "source_path": page.source_path,
        },
    )


def _write_page_plugins_used(
    page: Entity,
    page_dir: Path,
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
) -> None:
    """Write plugins.json for a page listing plugin action types used in its workflows."""
    workflows = extract_page_workflows(page)
    used_plugins = collect_plugin_action_types_from_workflows(workflows)
    page_slug = _file_stem(page.source_name, page.source_id)
    payload = {
        "page_slug": page_slug,
        "page_name": page.source_name,
        "used_plugins": used_plugins,
    }
    _write_json(
        page_dir / "plugins.json",
        payload,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "page_plugins_used",
            "source_id": page.source_id,
            "source_name": page.source_name,
            "source_path": page.source_path,
        },
    )


def _write_reusable_plugins_used(
    reusable: Entity,
    reusable_dir: Path,
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
) -> None:
    """Write plugins.json for a reusable listing plugin action types used in its workflows."""
    workflows = extract_reusable_workflows(reusable)
    used_plugins = collect_plugin_action_types_from_workflows(workflows)
    reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
    payload = {
        "reusable_slug": reusable_slug,
        "reusable_name": reusable.source_name,
        "used_plugins": used_plugins,
    }
    _write_json(
        reusable_dir / "plugins.json",
        payload,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "reusable_plugins_used",
            "source_id": reusable.source_id,
            "source_name": reusable.source_name,
            "source_path": reusable.source_path,
        },
    )


def _write_page_data_types_used(
    page: Entity,
    page_dir: Path,
    data_types: list[Entity],
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
) -> None:
    """Write data_types.json for a page listing data types referenced in its entity and workflows."""
    refs: Counter[str] = Counter()
    refs += _collect_thing_type_refs(page.raw)
    for workflow in extract_page_workflows(page):
        refs += _collect_thing_type_refs(workflow.raw)
    data_type_by_id = {e.source_id: e for e in data_types if e.source_id}
    used_data_types = []
    for source_id in sorted(refs.keys()):
        dt = data_type_by_id.get(source_id)
        if dt is None:
            continue
        slug = _file_stem(dt.source_name, dt.source_id)
        used_data_types.append({
            "data_type_source_id": source_id,
            "data_type_name": dt.source_name,
            "data_type_path": f"data_types/{slug}.json",
            "occurrence_count": refs[source_id],
        })
    page_slug = _file_stem(page.source_name, page.source_id)
    payload = {
        "page_slug": page_slug,
        "page_name": page.source_name,
        "used_data_types": used_data_types,
    }
    _write_json(
        page_dir / "data_types.json",
        payload,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "page_data_types_used",
            "source_id": page.source_id,
            "source_name": page.source_name,
            "source_path": page.source_path,
        },
    )


def _write_reusable_data_types_used(
    reusable: Entity,
    reusable_dir: Path,
    data_types: list[Entity],
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
) -> None:
    """Write data_types.json for a reusable listing data types referenced in its entity and workflows."""
    refs: Counter[str] = Counter()
    refs += _collect_thing_type_refs(reusable.raw)
    for workflow in extract_reusable_workflows(reusable):
        refs += _collect_thing_type_refs(workflow.raw)
    data_type_by_id = {e.source_id: e for e in data_types if e.source_id}
    used_data_types = []
    for source_id in sorted(refs.keys()):
        dt = data_type_by_id.get(source_id)
        if dt is None:
            continue
        slug = _file_stem(dt.source_name, dt.source_id)
        used_data_types.append({
            "data_type_source_id": source_id,
            "data_type_name": dt.source_name,
            "data_type_path": f"data_types/{slug}.json",
            "occurrence_count": refs[source_id],
        })
    reusable_slug = _file_stem(reusable.source_name, reusable.source_id)
    payload = {
        "reusable_slug": reusable_slug,
        "reusable_name": reusable.source_name,
        "used_data_types": used_data_types,
    }
    _write_json(
        reusable_dir / "data_types.json",
        payload,
        writes,
        dry_run,
        output_dir=output_dir,
        record_meta={
            "entity_type": "reusable_data_types_used",
            "source_id": reusable.source_id,
            "source_name": reusable.source_name,
            "source_path": reusable.source_path,
        },
    )


def _write_entity_group(entities: list[Entity], directory: Path, dry_run: bool, output_dir: Path) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    for entity in entities:
        filename = f"{_file_stem(entity.source_name, entity.source_id)}.json"
        payload_data = entity.raw
        if entity.entity_type == "data_type":
            payload_data = _normalize_data_type_fields(entity.raw)
        if entity.entity_type == "workflow":
            payload_data = _normalize_backend_workflow_fields(entity.raw, entity.source_name)
        payload = {"meta": _entity_meta(entity), "data": payload_data}
        _write_json(directory / filename, payload, writes, dry_run, output_dir=output_dir, record_meta=_entity_meta(entity))
    return writes


def _entity_meta(entity: Entity) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "entity_type": entity.entity_type,
        "source_id": entity.source_id,
        "source_name": entity.source_name,
        "source_path": entity.source_path,
    }
    if entity.entity_type == "data_type":
        meta["display_name"] = entity.source_name
        legacy_name = str(entity.raw.get("name", "")).strip()
        if legacy_name and legacy_name != entity.source_name:
            meta["legacy_name"] = legacy_name
    return meta


def _write_element_chunks(
    elements: list[dict[str, Any]],
    entity: Entity,
    page_dir: Path,
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
    entity_type: str,
) -> None:
    chunks = [elements[idx : idx + ELEMENTS_CHUNK_SIZE] for idx in range(0, len(elements), ELEMENTS_CHUNK_SIZE)]
    if not chunks:
        chunks = [[]]
    for idx, chunk in enumerate(chunks, start=1):
        _write_json(
            page_dir / "elements" / f"part-{idx:04d}.json",
            chunk,
            writes,
            dry_run,
            output_dir=output_dir,
            record_meta={
                "entity_type": entity_type,
                "source_id": entity.source_id,
                "source_name": entity.source_name,
                "source_path": entity.source_path,
                "chunk_index": idx,
                "chunk_total": len(chunks),
            },
        )


def _prune_noise(node: Any) -> Any:
    """Recursively remove empty dicts/lists/strings, nulls, and purely UI-centric editor noise."""
    if isinstance(node, dict):
        noisy_keys = {"is_slidable", "folded", "collapsed"}
        cleaned = {}
        for k, v in node.items():
            if k in noisy_keys:
                continue
            pruned_v = _prune_noise(v)
            # Only keep if not functionally 'empty'
            # Note: 0 and False evaluate to False in Python, but we want to retain them!
            if pruned_v or pruned_v is False or pruned_v == 0:
                cleaned[k] = pruned_v
        return cleaned
    if isinstance(node, list):
        cleaned_list = []
        for item in node:
            pruned_item = _prune_noise(item)
            if pruned_item or pruned_item is False or pruned_item == 0:
                cleaned_list.append(pruned_item)
        return cleaned_list
    return node


def _write_json(
    path: Path,
    payload: Any,
    writes: list[dict[str, Any]],
    dry_run: bool,
    *,
    output_dir: Path,
    record_meta: dict[str, Any] | None = None,
) -> None:
    # Protect against mutation of the source NormalizedExport
    # by deep-copying if we are about to inject AI interpretations.
    target_payload = payload
    if isinstance(payload, dict) and "data" in payload:
        target_payload = copy.deepcopy(payload)
        inject_ast_interpretations(target_payload["data"])

    target_payload = _prune_noise(target_payload)

    content = json.dumps(target_payload, indent=2, ensure_ascii=False)
    write_record: dict[str, Any] = {
        "path": to_output_relative_path(path, output_dir),
        "bytes": len(content.encode("utf-8")),
    }
    if record_meta:
        write_record.update(record_meta)
    writes.append(write_record)

    if dry_run:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_text(
    path: Path,
    payload: str,
    writes: list[dict[str, Any]],
    dry_run: bool,
    output_dir: Path,
    record_meta: dict[str, Any] | None = None,
) -> None:
    write_record: dict[str, Any] = {
        "path": to_output_relative_path(path, output_dir),
        "bytes": len(payload.encode("utf-8")),
    }
    if record_meta:
        write_record.update(record_meta)
    writes.append(write_record)
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _file_stem(name: str, stable_value: str) -> str:
    slug = _slugify(name)
    digest = hashlib.sha1(stable_value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "item"


def _normalize_data_type_fields(raw: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(raw)
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return payload

    flat_schema = {}
    for field_key, field_value in fields.items():
        if not isinstance(field_value, dict):
            continue
        display_name = field_value.get("display")
        if display_name is None or not str(display_name).strip():
            display_name = str(field_key)
        field_value["display_name"] = str(display_name)
        field_value["legacy_key"] = str(field_key)
        
        field_type = field_value.get("value") or field_value.get("type") or "unknown"
        is_list = field_value.get("list") or field_value.get("is_list")
        if isinstance(field_type, str) and field_type.startswith("custom."):
            field_type = field_type[7:]
            
        schema_type_str = f"list[{field_type}]" if is_list else str(field_type)
        flat_schema[str(display_name)] = schema_type_str

    if flat_schema:
        payload["__ai_flat_schema__"] = flat_schema

    return payload


def _normalize_backend_workflow_fields(raw: dict[str, Any], source_name: str) -> dict[str, Any]:
    payload = copy.deepcopy(raw)
    if source_name.strip():
        payload["name"] = source_name
    return payload

