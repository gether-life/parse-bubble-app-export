# Architectural Decisions

## 1. Directory-Based Decomposition
- **Decision**: Split the monolithic export into isolated folders per component (Pages, Reusables, Datatypes, Workflows, APIs).
- **Rationale**: Large Bubble exports can be hundreds of MBs. Loading the whole thing in memory or an LLM context is impossible. Folders allow agents to perform targeted, isolated semantic reads.

## 2. Manifest-First Traversal
- **Decision**: All entities must be indexed in `system/manifest.json`.
- **Rationale**: Prevents agents from guessing file paths and ensures that every file has a clear origin.

## 3. Gap ID Stability
- **Decision**: Gap IDs should be stable across runs if the source hasn't changed.
- **Rationale**: Allows migration trackers to reference specific gaps without them "moving" or changing IDs between daily parses.

## 4. Entity Parentage in Gaps
- **Decision**: Include `parent_entity_name` in gap records.
- **Rationale**: Gaps often occur deep within an element tree. Knowing that a missing reference is on the "Header" reusable across all pages is more actionable than knowing it's at `elements[15].reference`.

## 5. Agent-Optimized Artifacts
- **Decision**: Create `app_overview.md` and `app_counts.md`.
- **Rationale**: These are high-level entry points specifically for AI agents to understand the app semantics and scale parameters.
