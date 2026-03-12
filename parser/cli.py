from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .agent_index import build_agent_index_payloads, write_agent_index_files
from .apis import write_api_inventory_files
from .follow_up import generate_gap_report, write_gap_files
from .loader import load_export_bundle
from .manifest import build_manifest, manifest_path
from .normalizer import normalize_export
from .plugins import write_plugin_inventory_files
from .splitter import split_export


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split Bubble export into migration-friendly artifacts.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("input"),
        help="Input file or directory containing .json/.bubble/.zip export.",
    )
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when blocker severity gaps are found.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print write plan without creating files.",
    )
    parser.add_argument(
        "--ignore-gaps-file",
        type=Path,
        default=None,
        help="Optional path to newline-delimited or JSON-list gap IDs to suppress.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if not args.dry_run:
        _reset_output_directory(args.output)

    raw, supplemental_inputs = load_export_bundle(args.input)
    if not args.dry_run:
        _copy_supplemental_files(args.input, args.output, supplemental_inputs)

    normalized = normalize_export(raw, supplemental_inputs=supplemental_inputs)

    writes = split_export(normalized, args.output, dry_run=args.dry_run)
    ignored_gap_ids = _load_ignored_gap_ids(getattr(args, "ignore_gaps_file", None))
    gaps = generate_gap_report(normalized, ignored_gap_ids=ignored_gap_ids)
    writes.extend(write_gap_files(gaps, args.output, dry_run=args.dry_run))
    writes.extend(write_api_inventory_files(normalized, args.output, dry_run=args.dry_run))
    writes.extend(write_plugin_inventory_files(normalized, args.output, dry_run=args.dry_run))

    manifest = build_manifest(normalized, writes, gaps)
    agent_index_payloads = build_agent_index_payloads(normalized, writes, gaps, manifest)
    writes.extend(write_agent_index_files(agent_index_payloads, args.output, dry_run=args.dry_run))
    manifest = build_manifest(normalized, writes, gaps)
    manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
    if args.dry_run:
        # The instruction provided a syntactically incorrect line:
        # "system/api_contracts.json": "",   else:
        # Assuming the intent was to add this to the manifest for dry-run output,
        # but it's already dumped. Printing the manifest_json is the dry-run action.
        # The original instruction was likely malformed.
        # To make the file syntactically correct, this line cannot be inserted as is.
        # If the intent was to add this to the manifest, it should be done before json.dumps.
        # For now, I will assume the instruction was to simply print the manifest_json
        # and the problematic line was a mistake in the instruction.
        print(manifest_json)
    else:
        out_path = manifest_path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(manifest_json, encoding="utf-8")
        print(f"Wrote artifacts to {args.output}")
        print(f"Manifest: {out_path}")

    blocker_count = sum(1 for g in gaps if g.severity == "blocker")
    if args.strict and blocker_count > 0:
        print(f"Strict mode enabled: found {blocker_count} blocker gaps.", file=sys.stderr)
        return 2
    return 0


def _copy_supplemental_files(input_path: Path, output_dir: Path, supplemental_inputs: dict[str, Any]) -> None:
    loaded_files = supplemental_inputs.get("loaded_files", [])
    if not loaded_files:
        return

    # Determine original directory where supplemental files were found
    # (Matching logic in loader.py)
    if input_path.is_dir():
        directory = input_path
    else:
        # If input is a file, loader looks in its parent
        from .loader import discover_input_file
        try:
            source = discover_input_file(input_path)
            directory = source.parent
        except Exception:
            # Fallback if discovery fails (shouldn't happen here as load_export_bundle succeeded)
            directory = input_path.parent

    for rel_path_str in loaded_files:
        src = directory / rel_path_str
        dst = output_dir / "system" / rel_path_str
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _reset_output_directory(output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    unsafe_targets = {
        Path("/").resolve(),
        Path.home().resolve(),
        Path.cwd().resolve(),
    }
    repo_root = _find_repo_root(Path.cwd().resolve())
    if repo_root is not None:
        unsafe_targets.add(repo_root)
    if output_dir in unsafe_targets:
        raise ValueError(f"Refusing to clear unsafe output directory: {output_dir}")

    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError(f"Output path exists but is not a directory: {output_dir}")
        
        # Clear contents instead of deleting the directory itself
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    else:
        output_dir.mkdir(parents=True, exist_ok=True)


def _find_repo_root(start_dir: Path) -> Path | None:
    for candidate in [start_dir, *start_dir.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _load_ignored_gap_ids(ignore_file: Path | None) -> set[str]:
    if ignore_file is None:
        return set()
    if not ignore_file.exists():
        raise ValueError(f"Ignore gaps file does not exist: {ignore_file}")

    text = ignore_file.read_text(encoding="utf-8").strip()
    if not text:
        return set()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        return {str(item).strip() for item in parsed if str(item).strip()}
    if isinstance(parsed, dict):
        values = parsed.get("ignored_gap_ids")
        if isinstance(values, list):
            return {str(item).strip() for item in values if str(item).strip()}

    return {line.strip() for line in text.splitlines() if line.strip()}


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()

