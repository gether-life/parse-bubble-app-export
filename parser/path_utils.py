"""Helpers for output path handling (relative to output root for portable bundles)."""
from __future__ import annotations

from pathlib import Path


def to_output_relative_path(path: Path, output_dir: Path) -> str:
    """Return path as relative to output_dir, with forward slashes (portable)."""
    resolved_path = path.resolve()
    resolved_output = output_dir.resolve()
    return resolved_path.relative_to(resolved_output).as_posix()
