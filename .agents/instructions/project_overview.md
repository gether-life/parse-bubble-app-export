# Project Overview: Bubble Export Parser

## Purpose
The **Bubble Export Parser** is a Python CLI tool designed to decompose large Bubble.io app exports into smaller, deterministic, and highly searchable JSON/Markdown artifacts. It is optimized for AI agents to migrate or rebuild Bubble apps in modern stacks.

## Core Philosophy
1. **Deterministic Outputs**: Every run on the same input should produce identical output files (unless intentionally changed).
2. **One Entity Per File**: Pages, workflows, and data types are split into separate files for better searchability and context management.
3. **Traceability**: Every output file is linked back to the source JSON in `system/manifest.json`.
4. **Follow-Up (Gap Audit)**: Automatically identifies potential risks like unresolved references or black-box plugins.

## Stack
- **Language**: Python 3.10+
- **Input**: `.json`, `.bubble`, or `.zip` exports from Bubble.io.
- **Output**: A portable directory containing structured JSON and markdown components optimized for agents (`app_overview.md`, `app_counts.md`, `system/manifest.json`).

## Key Concepts
- **Entity**: A top-level Bubble object (Page, Reusable, Data Type, Workflow, or Integration).
- **Gap**: A migration risk or missing piece of information detected during parsing.
- **Manifest**: The system index (`system/manifest.json`) that maps everything.
