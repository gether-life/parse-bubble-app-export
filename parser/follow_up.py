from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import Entity, GapItem, NormalizedExport
from .path_utils import to_output_relative_path
from .normalizer import extract_page_workflows, extract_reusable_workflows

API_CONNECTOR_TYPE_RE = re.compile(r"^apiconnector2-([A-Za-z0-9]+)\.([A-Za-z0-9]+)$")

# Prefixes in api_friendly_names that indicate a known public API (method/URL look-up-able).
KNOWN_PUBLIC_API_PREFIXES = (
    "Stripe",
    "Google",
    "Bubble - ",
    "Serp - ",
    "Twilio",
    "Apple",
    "Microsoft",
)


def generate_gap_report(
    normalized: NormalizedExport,
    ignored_gap_ids: set[str] | None = None,
) -> list[GapItem]:
    gaps: list[GapItem] = []

    entities = _all_entities(normalized)
    known_ids = _collect_known_ids(entities)
    swagger_index = _build_swagger_operation_index(normalized.swagger_contract)

    if normalized.unknown_sections:
        gaps.append(
            _gap(
                category="unknown_section",
                severity="medium",
                where_found="root",
                evidence=f"Unknown top-level sections: {', '.join(normalized.unknown_sections)}",
                impact="Some exported data may not be processed into output artifacts.",
                recommended_action="Review and map these sections in normalizer aliases.",
            )
        )

    for warning in normalized.section_shape_warnings:
        gaps.append(
            _gap(
                category="unsupported_section_shape",
                severity="high",
                where_found="root",
                evidence=warning,
                impact="A section could not be parsed due to unsupported shape.",
                recommended_action="Inspect the raw section and add parser support.",
            )
        )

    for entity in entities:
        gaps.extend(_detect_entity_identifier_gaps(entity))
        gaps.extend(_detect_unresolved_references(entity, known_ids))
        gaps.extend(_detect_plugin_opaque_logic(entity))
        gaps.extend(_detect_external_api_without_contract(entity, swagger_index))

    deduped = _dedupe_gaps(gaps)
    enriched = _attach_gap_context(deduped, entities)
    if not ignored_gap_ids:
        return enriched
    return [gap for gap in enriched if gap.id not in ignored_gap_ids]


def write_gap_files(gaps: list[GapItem], output_dir: Path, dry_run: bool = False) -> list[dict[str, Any]]:
    payload = [gap.__dict__ for gap in gaps]
    grouped_by_severity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for gap in payload:
        grouped_by_severity[gap["severity"]].append(gap)
        grouped_by_category[gap["category"]].append(gap)

    gap_root = output_dir / "follow_up"
    writes = []
    for severity, items in grouped_by_severity.items():
        path = gap_root / "by_severity" / f"{severity}.json"
        writes.append(_gap_write_record(path, items, f"follow_up_gaps_severity_{severity}", output_dir=output_dir))
    for category, items in grouped_by_category.items():
        path = gap_root / "by_category" / f"{category}.json"
        writes.append(_gap_write_record(path, items, f"follow_up_gaps_category_{category}", output_dir=output_dir))

    if not dry_run:
        for severity, items in grouped_by_severity.items():
            path = gap_root / "by_severity" / f"{severity}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        for category, items in grouped_by_category.items():
            path = gap_root / "by_category" / f"{category}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return writes


def _all_entities(normalized: NormalizedExport) -> list[Entity]:
    out = []
    out.extend(normalized.pages)
    for page in normalized.pages:
        out.extend(extract_page_workflows(page))
    out.extend(normalized.data_types)
    out.extend(normalized.workflows)
    out.extend(normalized.reusables)
    for reusable in normalized.reusables:
        out.extend(extract_reusable_workflows(reusable))
    out.extend(normalized.privacy_rules)
    return out


def _collect_known_ids(entities: list[Entity]) -> set[str]:
    known_ids = {e.source_id for e in entities if e.source_id and not e.source_id.startswith("missing-")}
    for entity in entities:
        known_ids.update(_collect_ids_from_node(entity.raw))
    return known_ids


def _collect_ids_from_node(node: Any) -> set[str]:
    known_ids: set[str] = set()
    id_keys = {"id", "_id", "uid", "unique_id"}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in id_keys and isinstance(value, str) and value.strip():
                known_ids.add(value.strip())
            known_ids.update(_collect_ids_from_node(value))
    elif isinstance(node, list):
        for item in node:
            known_ids.update(_collect_ids_from_node(item))
    return known_ids


def _detect_entity_identifier_gaps(entity: Entity) -> list[GapItem]:
    gaps: list[GapItem] = []
    if entity.source_id.startswith("missing-"):
        gaps.append(
            _gap(
                category="missing_identifier",
                severity="high",
                where_found=entity.source_path,
                evidence=f"{entity.entity_type} has no stable source id.",
                impact="File identity may drift between runs and break migration traceability.",
                recommended_action="Locate a stable identifier in raw export and map it in normalizer.",
            )
        )
    if not entity.source_name.strip():
        gaps.append(
            _gap(
                category="missing_name",
                severity="medium",
                where_found=entity.source_path,
                evidence=f"{entity.entity_type} has no non-empty name.",
                impact="Generated filenames become less readable for migration.",
                recommended_action="Use a fallback naming rule or map a better display field.",
            )
        )
    return gaps


def _detect_unresolved_references(entity: Entity, known_ids: set[str]) -> list[GapItem]:
    gaps: list[GapItem] = []
    for key_path, value in _iter_key_paths(entity.raw):
        if not isinstance(value, str) or not value.strip():
            continue
        key_lower = key_path.split(".")[-1].lower()
        is_ref, severity = _reference_key_severity(key_lower)
        if not is_ref:
            continue
        if not _looks_like_static_identifier(value):
            continue
        if _looks_like_bubble_type_token(value):
            continue
        if value in known_ids:
            continue
        gaps.append(
            _gap(
                category="missing_reference",
                severity=severity,
                where_found=f"{entity.source_path}.{key_path}",
                evidence=f"Reference '{value}' not found in known entity ids.",
                impact="Migration cannot reliably reconstruct this link.",
                recommended_action="Locate referenced entity in export or add explicit mapping.",
            )
        )
    return gaps


def _detect_plugin_opaque_logic(entity: Entity) -> list[GapItem]:
    groups: dict[str, list[str]] = {}  # evidence_value -> list of where_found
    for key_path, value in _iter_key_paths(entity.raw):
        if not isinstance(value, str):
            continue
        key_lower = key_path.lower()
        value_lower = value.lower()
        if "plugin" not in key_lower and "plugin" not in value_lower:
            continue
        if "code" in key_lower or "source" in key_lower:
            continue
        where = f"{entity.source_path}.{key_path}"
        # Group by value so identical plugin references collapse into one gap
        if value not in groups:
            groups[value] = []
        groups[value].append(where)

    gaps: list[GapItem] = []
    for value, locations in groups.items():
        count = len(locations)
        if count == 1:
            evidence = f"Plugin-related reference without visible implementation details: '{value}'."
            where_found = locations[0]
        else:
            evidence = f"Plugin-related reference without visible implementation details: '{value}' ({count} occurrences)."
            # Include first two locations for traceability
            extra = "; ".join(locations[:2])
            if len(locations) > 2:
                extra += f" (+{len(locations) - 2} more)"
            evidence += f" Locations: {extra}"
            where_found = locations[0]
        gaps.append(
            _gap(
                category="plugin_black_box",
                severity="high",
                where_found=where_found,
                evidence=evidence,
                impact="Behavior may depend on plugin internals unavailable in export.",
                recommended_action="Document plugin behavior manually and define code-side replacement.",
            )
        )
    return gaps


def _is_simple_link_only(endpoint_examples: list[str], connector_keys: list[str]) -> bool:
    """True if no API Connector is used and all examples are mailto: or plain https?:// (no API-style path)."""
    if connector_keys:
        return False
    if not endpoint_examples:
        return False  # Ambiguous; don't downgrade.
    api_path_markers = ("/api/", "/wf/", "/v1/", "/v2/")
    # Single path segments that are clearly static pages (not API slugs).
    static_page_segments = ("terms", "privacy", "about", "contact", "help", "faq")
    for s in endpoint_examples:
        s = (s or "").strip()
        if not s:
            continue
        if s.lower().startswith("mailto:"):
            continue
        if s.startswith("http://") or s.startswith("https://"):
            parsed = urlparse(s)
            path = (parsed.path or "").strip("/")
            if any(marker in ("/" + path + "/") for marker in api_path_markers):
                return False
            # Multiple path segments often indicate an API.
            if path.count("/") >= 1:
                return False
            # Single segment: only treat as simple if it looks like a static page.
            if path and path.lower() not in static_page_segments:
                return False
            continue
        # Unknown scheme or format.
        return False
    return True


def _external_contract_severity(
    connector_details: dict[str, Any],
    swagger_matches: dict[str, Any],
    endpoint_examples: list[str],
) -> tuple[str, str]:
    """Returns (severity, recommended_action) for external_contract_unknown gaps."""
    default_action = "Capture API contract details from docs/logs before migration."
    ui_rebuild_action = "Mention for UI rebuild; no API contract needed."
    if swagger_matches.get("operation_ids"):
        return ("low", default_action)
    friendly_names = connector_details.get("friendly_names") or []
    for name in friendly_names:
        if isinstance(name, str) and any(
            name.startswith(prefix) for prefix in KNOWN_PUBLIC_API_PREFIXES
        ):
            return ("low", default_action)
    if _is_simple_link_only(endpoint_examples, connector_details.get("keys") or []):
        return ("low", ui_rebuild_action)
    return ("high", default_action)


def _detect_external_api_without_contract(
    entity: Entity, swagger_index: list[dict[str, str]]
) -> list[GapItem]:
    endpoint_paths: list[str] = []
    endpoint_examples: list[str] = []
    method_paths: list[str] = []
    method_values: list[str] = []
    payload_paths: list[str] = []

    for key_path, value in _iter_nodes_with_paths(entity.raw):
        if _is_contract_endpoint_key(key_path):
            endpoint_paths.append(key_path)
            if isinstance(value, str) and value.strip():
                endpoint_examples.append(value.strip())
            elif isinstance(value, dict):
                extracted_literal = _extract_text_expression_literal(value)
                if extracted_literal:
                    endpoint_examples.append(extracted_literal)
        if _is_contract_method_key(key_path) and isinstance(value, str) and value.strip():
            method_paths.append(key_path)
            method_values.append(value.strip())
        if _is_contract_payload_key(key_path) and value:
            payload_paths.append(key_path)

    has_endpoint = bool(endpoint_paths)
    has_method = bool(method_paths)
    has_payload = bool(payload_paths)
    if has_endpoint and (not has_method or not has_payload):
        connector_details = _collect_api_connector_details(entity.raw)
        swagger_matches = _match_swagger_operations(
            endpoint_examples=endpoint_examples,
            method_values=method_values,
            swagger_index=swagger_index,
            api_friendly_names=connector_details["friendly_names"],
        )
        missing_parts: list[str] = []
        if not has_method:
            missing_parts.append("method")
        if not has_payload:
            missing_parts.append("payload_or_schema")
        deduped_examples = _dedupe_list(endpoint_examples)[:10]
        severity, recommended_action = _external_contract_severity(
            connector_details, swagger_matches, deduped_examples
        )
        return [
            _gap(
                category="external_contract_unknown",
                severity=severity,
                where_found=entity.source_path,
                evidence="External endpoint detected but method/payload contract appears incomplete.",
                impact="Integration migration may break due to unknown request/response shape.",
                recommended_action=recommended_action,
                contract_endpoint_paths=_dedupe_list(endpoint_paths),
                contract_endpoint_examples=deduped_examples,
                contract_method_paths=_dedupe_list(method_paths),
                contract_method_values=_dedupe_list(method_values)[:10],
                contract_payload_paths=_dedupe_list(payload_paths),
                contract_missing_parts=missing_parts,
                api_connector_keys=connector_details["keys"],
                api_collection_ids=connector_details["collection_ids"],
                api_call_ids=connector_details["call_ids"],
                api_friendly_names=connector_details["friendly_names"],
                swagger_operation_ids=swagger_matches["operation_ids"],
                swagger_operation_methods=swagger_matches["methods"],
                swagger_operation_paths=swagger_matches["paths"],
            )
        ]
    return []


def _iter_key_paths(node: Any, prefix: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            next_prefix = f"{prefix}.{k}" if prefix else str(k)
            yield from _iter_key_paths(v, next_prefix)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            next_prefix = f"{prefix}[{idx}]"
            yield from _iter_key_paths(item, next_prefix)
    else:
        yield prefix, node


def _iter_nodes_with_paths(node: Any, prefix: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield next_prefix, value
            yield from _iter_nodes_with_paths(value, next_prefix)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            next_prefix = f"{prefix}[{idx}]"
            yield next_prefix, item
            yield from _iter_nodes_with_paths(item, next_prefix)


def _reference_key_severity(key_lower: str) -> tuple[bool, str]:
    key = key_lower.replace("[", ".").split(".")[-1]
    if key == "btype_id":
        return False, "low"
    blocker_keys = {
        "id_ref",
        "reference_id",
        "parent_id",
        "page_id",
        "workflow_id",
        "datatype_id",
        "data_type_id",
        "reusable_id",
        "element_id",
        "thing_type_id",
    }
    if key in blocker_keys:
        return True, "blocker"
    if key.startswith("ref_"):
        return True, "high"
    # Generic *_id keys are often literals in Bubble expressions; limit to known entity-ish prefixes.
    if key.endswith("_id") and any(
        token in key for token in ("page_", "workflow_", "type_", "element_", "reusable_", "parent_")
    ):
        return True, "medium"
    return False, "low"


def _looks_like_static_identifier(value: str) -> bool:
    # Skip dynamic expression-like values to avoid false positives.
    if any(ch in value for ch in (" ", "(", ")", "{", "}", ":", ",")):
        return False
    return len(value) >= 2


def _looks_like_bubble_type_token(value: str) -> bool:
    normalized = value.strip().lower()
    primitive_types = {"text", "number", "boolean", "date", "file"}
    if normalized in primitive_types:
        return True
    return normalized.startswith(("custom.", "list.", "option.", "api_wf_data."))


def _iter_path_segments(key_path: str) -> list[str]:
    return [segment.lower() for segment in key_path.replace("[", ".").replace("]", "").split(".") if segment]


def _is_contract_endpoint_key(key_path: str) -> bool:
    segments = _iter_path_segments(key_path)
    if not segments:
        return False
    leaf = segments[-1]
    if leaf in {"url", "endpoint", "webhook", "in_url", "request_url", "api_url", "target_url"}:
        return True
    if leaf.endswith("_endpoint"):
        return True
    if leaf.endswith("_url") and not leaf.endswith("urls"):
        return True
    return "webhook" in leaf


def _is_contract_method_key(key_path: str) -> bool:
    segments = _iter_path_segments(key_path)
    if not segments:
        return False
    leaf = segments[-1]
    if leaf in {"method", "http_method", "request_method"}:
        return True
    return leaf.endswith("_method")


def _is_contract_payload_key(key_path: str) -> bool:
    segments = _iter_path_segments(key_path)
    if not segments:
        return False
    leaf = segments[-1]
    if leaf in {"schema", "payload", "body", "request_body", "payload_schema", "body_schema", "json_body"}:
        return True
    if leaf.endswith("_payload") or leaf.endswith("_schema"):
        return True
    return leaf.endswith("_body") and not leaf.endswith("_body_text")


def _dedupe_list(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _collect_api_connector_details(node: Any) -> dict[str, list[str]]:
    keys: list[str] = []
    collection_ids: list[str] = []
    call_ids: list[str] = []
    friendly_names: list[str] = []
    for _, value in _iter_nodes_with_paths(node):
        if not isinstance(value, dict):
            continue
        node_type = value.get("type")
        if not isinstance(node_type, str):
            continue
        match = API_CONNECTOR_TYPE_RE.match(node_type)
        if not match:
            continue
        collection_id, call_id = match.groups()
        keys.append(node_type)
        collection_ids.append(collection_id)
        call_ids.append(call_id)
        name_value = value.get("name")
        if isinstance(name_value, str) and name_value.strip():
            friendly_names.append(name_value.strip())
        param_api = _extract_text_expression_literal(value.get("properties", {}).get("_wf_param_api"))
        if param_api:
            friendly_names.append(param_api)
    return {
        "keys": _dedupe_list(keys),
        "collection_ids": _dedupe_list(collection_ids),
        "call_ids": _dedupe_list(call_ids),
        "friendly_names": _dedupe_list(friendly_names),
    }


def _extract_text_expression_literal(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if value.get("type") != "TextExpression":
        return None
    entries = value.get("entries")
    if isinstance(entries, dict):
        ordered_keys = sorted(
            entries.keys(),
            key=lambda item: (0, int(str(item))) if str(item).isdigit() else (1, str(item)),
        )
        parts = [entries[key] for key in ordered_keys]
    elif isinstance(entries, list):
        parts = entries
    else:
        return None
    literals = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not literals:
        return None
    return " ".join(literals)


def _build_swagger_operation_index(swagger_contract: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(swagger_contract, dict):
        return []
    paths = swagger_contract.get("paths")
    if not isinstance(paths, dict):
        return []

    method_names = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    out: list[dict[str, str]] = []
    for path_name, methods in paths.items():
        if not isinstance(path_name, str) or not isinstance(methods, dict):
            continue
        for method_name, operation in methods.items():
            method = str(method_name).lower()
            if method not in method_names or not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId") or f"{method.upper()} {path_name}")
            out.append(
                {
                    "path": path_name,
                    "method": method.upper(),
                    "operation_id": operation_id,
                }
            )
    return out


def _match_swagger_operations(
    endpoint_examples: list[str],
    method_values: list[str],
    swagger_index: list[dict[str, str]],
    api_friendly_names: list[str] | None = None,
) -> dict[str, list[str]]:
    if not endpoint_examples or not swagger_index:
        return {"operation_ids": [], "methods": [], "paths": []}

    requested_methods = {method.upper() for method in method_values if isinstance(method, str) and method.strip()}
    endpoint_paths = [_extract_path_candidate(url_or_path) for url_or_path in endpoint_examples]
    endpoint_paths = [item for item in endpoint_paths if item]

    operation_ids: list[str] = []
    methods: list[str] = []
    paths: list[str] = []
    for endpoint_path in endpoint_paths:
        for operation in swagger_index:
            if requested_methods and operation["method"] not in requested_methods:
                continue
            if not _paths_match(operation["path"], endpoint_path):
                continue
            operation_ids.append(operation["operation_id"])
            methods.append(operation["method"])
            paths.append(operation["path"])

    result = {
        "operation_ids": _dedupe_list(operation_ids),
        "methods": _dedupe_list(methods),
        "paths": _dedupe_list(paths),
    }
    if result["operation_ids"] or not api_friendly_names:
        return result

    fallback = _match_swagger_operations_by_name(
        api_friendly_names=api_friendly_names,
        method_values=method_values,
        swagger_index=swagger_index,
    )
    return fallback


def _match_swagger_operations_by_name(
    api_friendly_names: list[str],
    method_values: list[str],
    swagger_index: list[dict[str, str]],
) -> dict[str, list[str]]:
    requested_methods = {method.upper() for method in method_values if isinstance(method, str) and method.strip()}
    operation_ids: list[str] = []
    methods: list[str] = []
    paths: list[str] = []

    for raw_name in api_friendly_names:
        label_tokens = _tokenize_match_text(raw_name.split(" - ", 1)[-1] if " - " in raw_name else raw_name)
        if not label_tokens:
            continue
        best_operation: dict[str, str] | None = None
        best_overlap = 0
        for operation in swagger_index:
            if requested_methods and operation["method"] not in requested_methods:
                continue
            op_tokens = _tokenize_match_text(f"{operation['operation_id']} {operation['path']}")
            overlap = len(label_tokens.intersection(op_tokens))
            if overlap > best_overlap:
                best_overlap = overlap
                best_operation = operation
        if best_operation is None:
            continue
        # Require at least two overlapping tokens to avoid noisy matches.
        if best_overlap < 2:
            continue
        operation_ids.append(best_operation["operation_id"])
        methods.append(best_operation["method"])
        paths.append(best_operation["path"])

    return {
        "operation_ids": _dedupe_list(operation_ids),
        "methods": _dedupe_list(methods),
        "paths": _dedupe_list(paths),
    }


def _tokenize_match_text(value: str) -> set[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    lowered = camel_split.lower()
    chunks = re.split(r"[^a-z0-9]+", lowered)
    stop_words = {"api", "call", "get", "set", "the", "a", "an", "to", "for", "and"}
    return {chunk for chunk in chunks if chunk and len(chunk) > 1 and chunk not in stop_words}


def _extract_path_candidate(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return parsed.path or "/"
    if value.startswith("/"):
        return value
    return f"/{value}" if "/" in value else value


def _paths_match(swagger_path: str, observed_path: str) -> bool:
    swagger_parts = [part for part in swagger_path.strip("/").split("/") if part]
    observed_parts = [part for part in observed_path.strip("/").split("/") if part]
    if len(swagger_parts) != len(observed_parts):
        return False
    for swagger_part, observed_part in zip(swagger_parts, observed_parts):
        if swagger_part.startswith("{") and swagger_part.endswith("}"):
            continue
        if swagger_part != observed_part:
            return False
    return True


def _gap(
    category: str,
    severity: str,
    where_found: str,
    evidence: str,
    impact: str,
    recommended_action: str,
    contract_endpoint_paths: list[str] | None = None,
    contract_endpoint_examples: list[str] | None = None,
    contract_method_paths: list[str] | None = None,
    contract_method_values: list[str] | None = None,
    contract_payload_paths: list[str] | None = None,
    contract_missing_parts: list[str] | None = None,
    api_connector_keys: list[str] | None = None,
    api_collection_ids: list[str] | None = None,
    api_call_ids: list[str] | None = None,
    api_friendly_names: list[str] | None = None,
    swagger_operation_ids: list[str] | None = None,
    swagger_operation_methods: list[str] | None = None,
    swagger_operation_paths: list[str] | None = None,
) -> GapItem:
    stable = f"{category}|{where_found}|{evidence}"
    gap_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12]
    return GapItem(
        id=gap_id,
        category=category,
        severity=severity,
        where_found=where_found,
        evidence=evidence,
        impact=impact,
        recommended_action=recommended_action,
        contract_endpoint_paths=contract_endpoint_paths,
        contract_endpoint_examples=contract_endpoint_examples,
        contract_method_paths=contract_method_paths,
        contract_method_values=contract_method_values,
        contract_payload_paths=contract_payload_paths,
        contract_missing_parts=contract_missing_parts,
        api_connector_keys=api_connector_keys,
        api_collection_ids=api_collection_ids,
        api_call_ids=api_call_ids,
        api_friendly_names=api_friendly_names,
        swagger_operation_ids=swagger_operation_ids,
        swagger_operation_methods=swagger_operation_methods,
        swagger_operation_paths=swagger_operation_paths,
    )


def _dedupe_gaps(gaps: list[GapItem]) -> list[GapItem]:
    unique: dict[str, GapItem] = {}
    for gap in gaps:
        unique[gap.id] = gap
    return list(unique.values())


def _attach_gap_context(gaps: list[GapItem], entities: list[Entity]) -> list[GapItem]:
    index, sorted_paths = _build_context_index(entities)
    enriched: list[GapItem] = []
    for gap in gaps:
        context = _resolve_gap_context(gap.where_found, index, sorted_paths)
        enriched.append(
            GapItem(
                id=gap.id,
                category=gap.category,
                severity=gap.severity,
                where_found=gap.where_found,
                evidence=gap.evidence,
                impact=gap.impact,
                recommended_action=gap.recommended_action,
                entity_type=context.get("entity_type"),
                entity_source_id=context.get("entity_source_id"),
                entity_name=context.get("entity_name"),
                parent_entity_type=context.get("parent_entity_type"),
                parent_entity_source_id=context.get("parent_entity_source_id"),
                parent_entity_name=context.get("parent_entity_name"),
                contract_endpoint_paths=gap.contract_endpoint_paths,
                contract_endpoint_examples=gap.contract_endpoint_examples,
                contract_method_paths=gap.contract_method_paths,
                contract_method_values=gap.contract_method_values,
                contract_payload_paths=gap.contract_payload_paths,
                contract_missing_parts=gap.contract_missing_parts,
                api_connector_keys=gap.api_connector_keys,
                api_collection_ids=gap.api_collection_ids,
                api_call_ids=gap.api_call_ids,
                api_friendly_names=gap.api_friendly_names,
                swagger_operation_ids=gap.swagger_operation_ids,
                swagger_operation_methods=gap.swagger_operation_methods,
                swagger_operation_paths=gap.swagger_operation_paths,
            )
        )
    return enriched


def _build_context_index(
    entities: list[Entity],
) -> tuple[dict[str, dict[str, str | None]], list[str]]:
    entities_by_path = {entity.source_path: entity for entity in entities}
    index: dict[str, dict[str, str | None]] = {}
    for entity in entities:
        parent_path = _parent_source_path(entity.source_path)
        parent_entity = entities_by_path.get(parent_path) if parent_path else None
        index[entity.source_path] = {
            "entity_type": entity.entity_type,
            "entity_source_id": entity.source_id,
            "entity_name": entity.source_name,
            "parent_entity_type": parent_entity.entity_type if parent_entity else None,
            "parent_entity_source_id": parent_entity.source_id if parent_entity else None,
            "parent_entity_name": parent_entity.source_name if parent_entity else None,
        }
    sorted_paths = sorted(index.keys(), key=len, reverse=True)
    return index, sorted_paths


def _resolve_gap_context(
    where_found: str,
    index: dict[str, dict[str, str | None]],
    sorted_paths: list[str],
) -> dict[str, str | None]:
    if where_found in index:
        return index[where_found]
    for source_path in sorted_paths:
        if where_found.startswith(f"{source_path}.") or where_found.startswith(f"{source_path}["):
            return index[source_path]
    return {}


def _parent_source_path(source_path: str) -> str | None:
    if ".workflows[" in source_path:
        return source_path.split(".workflows[", maxsplit=1)[0]
    return None


def _to_markdown(gaps: list[GapItem]) -> str:
    if not gaps:
        return "# Follow-up Gaps\n\nNo gaps detected.\n"

    grouped: dict[str, list[GapItem]] = defaultdict(list)
    for gap in gaps:
        grouped[gap.severity].append(gap)

    order = ["blocker", "high", "medium", "low"]
    lines: list[str] = ["# Follow-up Gaps", ""]
    for severity in order:
        items = grouped.get(severity, [])
        if not items:
            continue
        lines.append(f"## {severity.title()} ({len(items)})")
        lines.append("")
        for gap in items:
            lines.append(f"- `{gap.id}` [{gap.category}] at `{gap.where_found}`")
            lines.append(f"  - evidence: {gap.evidence}")
            lines.append(f"  - impact: {gap.impact}")
            lines.append(f"  - action: {gap.recommended_action}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _to_folder_readme(summary: dict[str, Any]) -> str:
    lines = [
        "# Follow-up Gaps",
        "",
        "This folder contains follow-up gaps grouped for triage.",
        "",
        "## Files",
        "",
        "- `summary.json`: total counts by severity and category",
        "- `by_severity/*.json`: full gap entries grouped by severity",
        "- `by_category/*.json`: full gap entries grouped by category",
        "",
        "Each gap item includes readable context fields:",
        "- `entity_type`, `entity_source_id`, `entity_name`",
        "- `parent_entity_type`, `parent_entity_source_id`, `parent_entity_name`",
        "- `contract_*` fields for external contract diagnostics when relevant",
        "- `api_*` and `swagger_*` fields for API connector and contract traceability",
        "",
        "## Counts",
        "",
        f"- total: {summary.get('total', 0)}",
    ]
    for severity, count in sorted(summary.get("by_severity", {}).items()):
        lines.append(f"- severity `{severity}`: {count}")
    for category, count in sorted(summary.get("by_category", {}).items()):
        lines.append(f"- category `{category}`: {count}")
    return "\n".join(lines).rstrip() + "\n"


def _gap_write_record(
    path: Path, payload: Any, source_name: str, *, output_dir: Path, is_text: bool = False
) -> dict[str, Any]:
    if is_text:
        size = len(str(payload).encode("utf-8"))
    else:
        size = len(json.dumps(payload, ensure_ascii=False))
    return {
        "path": to_output_relative_path(path, output_dir),
        "bytes": size,
        "entity_type": "gap_report",
        "source_id": "",
        "source_name": source_name,
        "source_path": "root",
    }

