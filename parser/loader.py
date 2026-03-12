from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any


SUPPORTED_JSON_EXTENSIONS = {".json", ".bubble"}
SUPPLEMENTAL_API_FILES = {"swagger.json", "openapi.json"}


def discover_input_file(input_path: Path) -> Path:
    if input_path.is_file():
        return input_path

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    if not input_path.is_dir():
        raise ValueError(f"Input path must be a file or directory: {input_path}")

    candidates = [
        p
        for p in sorted(input_path.iterdir())
        if p.is_file()
        and p.name.lower() not in SUPPLEMENTAL_API_FILES
        and (p.suffix.lower() in SUPPORTED_JSON_EXTENSIONS or p.suffix.lower() == ".zip")
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No supported export file found in {input_path}. Expected .json, .bubble, or .zip."
        )
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple candidate input files found in {input_path}: {[p.name for p in candidates]}. "
            "Pass --input with an explicit file path."
        )
    return candidates[0]


def load_export(input_path: Path) -> dict[str, Any]:
    data, _ = load_export_bundle(input_path)
    return data


def load_export_bundle(input_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source = discover_input_file(input_path)
    if source.suffix.lower() == ".zip":
        data = _load_export_from_zip(source)
    else:
        text = source.read_text(encoding="utf-8")
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Expected top-level JSON object in Bubble export.")
    supplemental = _load_supplemental_inputs(source, input_path)
    return data, supplemental


def _load_export_from_zip(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as zf:
        json_entries = sorted(
            name for name in zf.namelist() if Path(name).suffix.lower() in SUPPORTED_JSON_EXTENSIONS
        )
        if not json_entries:
            raise ValueError(f"No .json/.bubble payload found in zip: {path}")
        payload_name = json_entries[0]
        with zf.open(payload_name, "r") as fh:
            raw = fh.read().decode("utf-8")
            data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Top-level payload in {path} is not a JSON object.")
    return data


def _load_supplemental_inputs(source: Path, original_input_path: Path) -> dict[str, Any]:
    directory = original_input_path if original_input_path.is_dir() else source.parent
    if not directory.exists() or not directory.is_dir():
        return {"loaded_files": []}

    loaded_files: list[str] = []
    swagger_contract: dict[str, Any] | None = None
    for filename in sorted(SUPPLEMENTAL_API_FILES):
        candidate = directory / filename
        if not candidate.exists() or not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Supplemental file {candidate} must be a JSON object.")
        try:
            rel = candidate.relative_to(directory)
            loaded_files.append(rel.as_posix())
        except ValueError:
            loaded_files.append(candidate.name)
        # Prefer swagger.json over openapi.json when both exist.
        if swagger_contract is None or candidate.name.lower() == "swagger.json":
            swagger_contract = parsed

    payload: dict[str, Any] = {"loaded_files": loaded_files}
    if swagger_contract is not None:
        payload["swagger_contract"] = swagger_contract
    return payload

