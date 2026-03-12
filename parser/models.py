from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JSONDict = dict[str, Any]


@dataclass(frozen=True)
class Entity:
    entity_type: str
    source_path: str
    source_id: str
    source_name: str
    raw: JSONDict


@dataclass
class NormalizedExport:
    raw: JSONDict
    app_meta: JSONDict
    supplemental_inputs: JSONDict = field(default_factory=dict)
    swagger_contract: JSONDict | None = None
    pages: list[Entity] = field(default_factory=list)
    data_types: list[Entity] = field(default_factory=list)
    workflows: list[Entity] = field(default_factory=list)
    reusables: list[Entity] = field(default_factory=list)
    privacy_rules: list[Entity] = field(default_factory=list)
    data_options: list[Entity] = field(default_factory=list)
    styles: list[Entity] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)
    section_shape_warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GapItem:
    id: str
    category: str
    severity: str
    where_found: str
    evidence: str
    impact: str
    recommended_action: str
    entity_type: str | None = None
    entity_source_id: str | None = None
    entity_name: str | None = None
    parent_entity_type: str | None = None
    parent_entity_source_id: str | None = None
    parent_entity_name: str | None = None
    contract_endpoint_paths: list[str] | None = None
    contract_endpoint_examples: list[str] | None = None
    contract_method_paths: list[str] | None = None
    contract_method_values: list[str] | None = None
    contract_payload_paths: list[str] | None = None
    contract_missing_parts: list[str] | None = None
    api_connector_keys: list[str] | None = None
    api_collection_ids: list[str] | None = None
    api_call_ids: list[str] | None = None
    api_friendly_names: list[str] | None = None
    swagger_operation_ids: list[str] | None = None
    swagger_operation_methods: list[str] | None = None
    swagger_operation_paths: list[str] | None = None

