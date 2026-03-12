# Output Contract & Structure

The parser writes to a portable directory. All internal paths are relative.

## Root Artifacts
- `system/`: The metadata core containing index maps (`element_id_map.json`, `workflow_map.json`) and the master source-of-truth index (`manifest.json`).
- `app_counts.md`: Statistical tracking parameters.
- `app_overview.md`: Semantic, narrative breakdowns.

## Directory Layout
- `/data_types/`: Each data type is a separate JSON file.
- `/pages/<slug>/`:
  - `entity.json`: The layout/meta for the page.
  - `elements/`: Decomposed UI tree (part-*.json).
  - `workflows/`: Page-specific workflows.
- `/reusables/<slug>/`: Same structure as pages.
- `/workflows/`: All standalone API and backend workflows.
- `/apis/`: Comprehensive list of all detected external calls and provider setups.
- `/plugins/`: Action types and occurrence mappings.
- `/follow_up/`: Grouped migration risks by severity and category.
- `/data_privacy/`: Security rules per data type.
- `/styles/` & `/data_options/`: Application style tokens and option sets.

## Audit Indicators
Gaps are categorized as:
- **Blocker**: Critical architectural missing pieces.
- **Warning**: Potential manual triage needed.
- **Info**: Contextual notes for the migration.
