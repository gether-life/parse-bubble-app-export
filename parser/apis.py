from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from .models import Entity, NormalizedExport
from .path_utils import to_output_relative_path
from .normalizer import extract_page_workflows, extract_reusable_workflows

API_CONNECTOR_TYPE_RE = re.compile(r"^apiconnector2-([A-Za-z0-9]+)\.([A-Za-z0-9]+)$")


def build_api_inventory(normalized: NormalizedExport) -> dict[str, Any]:
    swagger_index = _build_swagger_operation_index(normalized.swagger_contract)
    calls: list[dict[str, Any]] = []

    for page in normalized.pages:
        for workflow in extract_page_workflows(page):
            calls.extend(
                _extract_calls_from_workflow(
                    workflow=workflow,
                    parent_entity=page,
                    source_kind="page_workflow",
                    swagger_index=swagger_index,
                )
            )

    for reusable in normalized.reusables:
        for workflow in extract_reusable_workflows(reusable):
            calls.extend(
                _extract_calls_from_workflow(
                    workflow=workflow,
                    parent_entity=reusable,
                    source_kind="reusable_workflow",
                    swagger_index=swagger_index,
                )
            )

    for workflow in normalized.workflows:
        calls.extend(
            _extract_calls_from_workflow(
                workflow=workflow,
                parent_entity=None,
                source_kind="backend_workflow",
                swagger_index=swagger_index,
            )
        )

    calls = sorted(calls, key=lambda item: item["call_id"])
    by_api: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for call in calls:
        by_api[_api_group_key(call)].append(call)

    for key in list(by_api.keys()):
        by_api[key] = sorted(by_api[key], key=lambda item: item["call_id"])

    summary = _build_summary(calls)
    return {
        "summary": summary,
        "calls": calls,
        "by_api": dict(sorted(by_api.items(), key=lambda item: item[0])),
    }


def write_api_inventory_files(
    normalized: NormalizedExport, output_dir: Path, dry_run: bool = False
) -> list[dict[str, Any]]:
    inventory = build_api_inventory(normalized)
    root = output_dir / "apis"
    calls_path = root / "calls.json"

    writes: list[dict[str, Any]] = []
    _write_json(calls_path, inventory["calls"], writes, dry_run, output_dir, source_name="api_inventory_calls")

    for api_key, api_calls in inventory["by_api"].items():
        slug = _slugify(api_key)
        path = root / "by_api" / f"{slug}.json"
        _write_json(path, api_calls, writes, dry_run, output_dir, source_name=f"api_inventory_by_api_{slug}")

    return writes


def _extract_calls_from_workflow(
    workflow: Entity,
    parent_entity: Entity | None,
    source_kind: str,
    swagger_index: list[dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    actions = workflow.raw.get("actions")
    action_items = _coerce_actions(actions)

    for action_index, action in action_items:
        action_type = action.get("type")
        if not isinstance(action_type, str):
            continue

        properties = action.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        evidence = _collect_request_evidence(properties)
        connector_match = API_CONNECTOR_TYPE_RE.match(action_type)
        is_connector = connector_match is not None
        is_request_like = evidence["has_endpoint"] and (
            evidence["has_method"]
            or evidence["has_payload"]
            or evidence["has_headers"]
            or evidence["has_params"]
            or is_connector
        )
        if not is_connector and not is_request_like:
            continue

        api_collection_id = connector_match.group(1) if connector_match else None
        api_call_id = connector_match.group(2) if connector_match else None
        api_name = _choose_api_name(action=action, properties=properties, action_type=action_type)

        method_literal = evidence["method_literal"]
        if isinstance(method_literal, str):
            method_literal = method_literal.upper()
        url_literal = evidence["endpoint_literal"]
        path = _extract_path_candidate(url_literal) if isinstance(url_literal, str) and url_literal else None
        query_params = _extract_query_params(url_literal)

        swagger_matches = _match_swagger_operations(
            endpoint_examples=[url_literal] if isinstance(url_literal, str) and url_literal else [],
            method_values=[method_literal] if isinstance(method_literal, str) and method_literal else [],
            swagger_index=swagger_index,
            api_friendly_names=[api_name] if api_name else [],
        )

        stable = "|".join(
            [
                str(workflow.source_path),
                str(action.get("id", "")),
                str(action_index),
                str(action_type),
                str(api_name),
            ]
        )
        call_id = hashlib.sha1(stable.encode("utf-8")).hexdigest()[:12]

        out.append(
            {
                "call_id": call_id,
                "source_kind": source_kind,
                "entity_type": workflow.entity_type,
                "workflow_name": workflow.source_name,
                "workflow_source_id": workflow.source_id,
                "workflow_source_path": workflow.source_path,
                "workflow_output_path": _workflow_output_path(workflow, parent_entity, source_kind),
                "parent_entity_type": parent_entity.entity_type if parent_entity else None,
                "parent_entity_name": parent_entity.source_name if parent_entity else None,
                "parent_entity_source_id": parent_entity.source_id if parent_entity else None,
                "action_index": action_index,
                "action_id": action.get("id"),
                "action_name": action.get("name"),
                "action_type": action_type,
                "api_name": api_name,
                "api_connector_key": action_type if is_connector else None,
                "api_collection_id": api_collection_id,
                "api_call_id": api_call_id,
                "provider": _provider_name(api_name, url_literal),
                "method_literal": method_literal,
                "method_raw": evidence["method_raw"],
                "url_literal": url_literal,
                "url_raw": evidence["endpoint_raw"],
                "path": path,
                "query_params": query_params,
                "headers_raw": evidence["headers_raw"],
                "params_raw": evidence["params_raw"],
                "payload_raw": evidence["payload_raw"],
                "payload_format": _payload_format(evidence),
                "evidence": evidence["evidence"],
                "swagger_operation_ids": swagger_matches["operation_ids"],
                "swagger_operation_methods": swagger_matches["methods"],
                "swagger_operation_paths": swagger_matches["paths"],
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


def _collect_request_evidence(properties: dict[str, Any]) -> dict[str, Any]:
    endpoint_hits: list[tuple[str, Any]] = []
    method_hits: list[tuple[str, Any]] = []
    payload_hits: list[tuple[str, Any]] = []
    headers_hits: list[tuple[str, Any]] = []
    params_hits: list[tuple[str, Any]] = []

    for key_path, value in _iter_nodes_with_paths(properties):
        if _is_endpoint_key(key_path):
            endpoint_hits.append((key_path, value))
        if _is_method_key(key_path):
            method_hits.append((key_path, value))
        if _is_payload_key(key_path):
            payload_hits.append((key_path, value))
        if _is_headers_key(key_path):
            headers_hits.append((key_path, value))
        if _is_params_key(key_path):
            params_hits.append((key_path, value))

    endpoint_path, endpoint_raw, endpoint_literal = _best_value(endpoint_hits)
    method_path, method_raw, method_literal = _best_value(method_hits)
    _, headers_raw, _ = _best_value(headers_hits)
    _, params_raw, _ = _best_value(params_hits)
    _, payload_raw, _ = _best_value(payload_hits)

    return {
        "has_endpoint": bool(endpoint_hits),
        "has_method": bool(method_hits),
        "has_payload": bool(payload_hits),
        "has_headers": bool(headers_hits),
        "has_params": bool(params_hits),
        "endpoint_raw": endpoint_raw,
        "endpoint_literal": endpoint_literal,
        "method_raw": method_raw,
        "method_literal": method_literal,
        "headers_raw": headers_raw,
        "params_raw": params_raw,
        "payload_raw": payload_raw,
        "evidence": {
            "endpoint_paths": [item[0] for item in endpoint_hits],
            "method_paths": [item[0] for item in method_hits],
            "headers_paths": [item[0] for item in headers_hits],
            "params_paths": [item[0] for item in params_hits],
            "payload_paths": [item[0] for item in payload_hits],
            "selected_endpoint_path": endpoint_path,
            "selected_method_path": method_path,
        },
    }


def _best_value(hits: list[tuple[str, Any]]) -> tuple[str | None, Any, str | None]:
    if not hits:
        return None, None, None
    path, value = hits[0]
    literal = _to_literal(value)
    return path, value, literal


def _to_literal(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return _extract_text_expression_literal(value)


def _choose_api_name(action: dict[str, Any], properties: dict[str, Any], action_type: str) -> str:
    action_name = action.get("name")
    if isinstance(action_name, str) and action_name.strip():
        return action_name.strip()
    param_api = _extract_text_expression_literal(properties.get("_wf_param_api"))
    if param_api:
        return param_api
    return action_type


def _provider_name(api_name: str | None, url_literal: str | None) -> str:
    if isinstance(api_name, str) and " - " in api_name:
        prefix = api_name.split(" - ", maxsplit=1)[0].strip()
        if prefix:
            return prefix
    if isinstance(url_literal, str) and url_literal.strip():
        netloc = urlparse(url_literal).netloc
        if netloc:
            return netloc
    return "unknown"


def _extract_query_params(url_literal: str | None) -> dict[str, str]:
    if not isinstance(url_literal, str) or not url_literal.strip():
        return {}
    parsed = urlparse(url_literal)
    if not parsed.query:
        return {}
    return {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}


def _payload_format(evidence: dict[str, Any]) -> str | None:
    payload_paths = evidence.get("evidence", {}).get("payload_paths", [])
    if not payload_paths:
        return None
    leaf = payload_paths[0].split(".")[-1].lower()
    if "json" in leaf or "schema" in leaf:
        return "json"
    if "body" in leaf or "payload" in leaf:
        return "body"
    return "unknown"


def _build_summary(calls: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = Counter(call.get("source_kind") for call in calls)
    by_provider = Counter(call.get("provider") for call in calls)
    by_method = Counter(call.get("method_literal") or "unknown" for call in calls)
    by_api = Counter(_api_group_key(call) for call in calls)

    complete_contract = 0
    for call in calls:
        if call.get("url_literal") and call.get("method_literal") and call.get("payload_raw") is not None:
            complete_contract += 1

    return {
        "total_calls": len(calls),
        "by_source_kind": dict(sorted(by_source.items())),
        "by_provider": dict(sorted(by_provider.items())),
        "by_method": dict(sorted(by_method.items())),
        "by_api": dict(sorted(by_api.items())),
        "contract_completeness": {
            "calls_with_url": sum(1 for call in calls if call.get("url_literal")),
            "calls_with_method": sum(1 for call in calls if call.get("method_literal")),
            "calls_with_headers": sum(1 for call in calls if call.get("headers_raw") is not None),
            "calls_with_params": sum(1 for call in calls if call.get("params_raw") is not None),
            "calls_with_payload": sum(1 for call in calls if call.get("payload_raw") is not None),
            "calls_with_full_request_contract": complete_contract,
        },
    }


def _api_group_key(call: dict[str, Any]) -> str:
    for key in ("api_name", "api_connector_key", "url_literal"):
        value = call.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown_api"


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


def _iter_path_segments(key_path: str) -> list[str]:
    return [segment.lower() for segment in key_path.replace("[", ".").replace("]", "").split(".") if segment]


def _is_endpoint_key(key_path: str) -> bool:
    leaf = _leaf(key_path)
    if leaf in {"url", "endpoint", "webhook", "in_url", "request_url", "api_url", "target_url"}:
        return True
    if leaf.endswith("_endpoint"):
        return True
    if leaf.endswith("_url") and not leaf.endswith("urls"):
        return True
    return "webhook" in leaf


def _is_method_key(key_path: str) -> bool:
    leaf = _leaf(key_path)
    if leaf in {"method", "http_method", "request_method"}:
        return True
    return leaf.endswith("_method")


def _is_payload_key(key_path: str) -> bool:
    leaf = _leaf(key_path)
    if leaf in {"schema", "payload", "body", "request_body", "payload_schema", "body_schema", "json_body"}:
        return True
    if leaf.endswith("_payload") or leaf.endswith("_schema"):
        return True
    return leaf.endswith("_body") and not leaf.endswith("_body_text")


def _is_headers_key(key_path: str) -> bool:
    leaf = _leaf(key_path)
    if leaf in {"headers", "header", "http_headers", "request_headers"}:
        return True
    return leaf.endswith("_headers")


def _is_params_key(key_path: str) -> bool:
    leaf = _leaf(key_path)
    if leaf in {"params", "query_params", "query", "querystring", "query_string"}:
        return True
    return leaf.endswith("_params")


def _leaf(key_path: str) -> str:
    segments = _iter_path_segments(key_path)
    return segments[-1] if segments else ""


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
            out.append({"path": path_name, "method": method.upper(), "operation_id": operation_id})
    return out


def _match_swagger_operations(
    endpoint_examples: list[str],
    method_values: list[str],
    swagger_index: list[dict[str, str]],
    api_friendly_names: list[str] | None = None,
) -> dict[str, list[str]]:
    if not swagger_index:
        return {"operation_ids": [], "methods": [], "paths": []}

    requested_methods = {method.upper() for method in method_values if isinstance(method, str) and method.strip()}
    operation_ids: list[str] = []
    methods: list[str] = []
    paths: list[str] = []

    endpoint_paths = [_extract_path_candidate(item) for item in endpoint_examples if isinstance(item, str)]
    endpoint_paths = [item for item in endpoint_paths if item]
    for endpoint_path in endpoint_paths:
        for operation in swagger_index:
            if requested_methods and operation["method"] not in requested_methods:
                continue
            if not _paths_match(operation["path"], endpoint_path):
                continue
            operation_ids.append(operation["operation_id"])
            methods.append(operation["method"])
            paths.append(operation["path"])

    if operation_ids or not api_friendly_names:
        return {
            "operation_ids": _dedupe(operation_ids),
            "methods": _dedupe(methods),
            "paths": _dedupe(paths),
        }

    return _match_swagger_operations_by_name(api_friendly_names, requested_methods, swagger_index)


def _match_swagger_operations_by_name(
    api_friendly_names: list[str],
    requested_methods: set[str],
    swagger_index: list[dict[str, str]],
) -> dict[str, list[str]]:
    operation_ids: list[str] = []
    methods: list[str] = []
    paths: list[str] = []

    for raw_name in api_friendly_names:
        label_tokens = _tokenize(raw_name.split(" - ", 1)[-1] if " - " in raw_name else raw_name)
        if not label_tokens:
            continue
        best: dict[str, str] | None = None
        best_overlap = 0
        for operation in swagger_index:
            if requested_methods and operation["method"] not in requested_methods:
                continue
            op_tokens = _tokenize(f"{operation['operation_id']} {operation['path']}")
            overlap = len(label_tokens.intersection(op_tokens))
            if overlap > best_overlap:
                best_overlap = overlap
                best = operation
        if best is None or best_overlap < 2:
            continue
        operation_ids.append(best["operation_id"])
        methods.append(best["method"])
        paths.append(best["path"])

    return {
        "operation_ids": _dedupe(operation_ids),
        "methods": _dedupe(methods),
        "paths": _dedupe(paths),
    }


def _tokenize(value: str) -> set[str]:
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


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


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
            "entity_type": "apis",
            "source_id": "",
            "source_name": source_name,
            "source_path": "root",
        }
    )
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")



