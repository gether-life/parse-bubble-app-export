# Bubble Export Parser

This project parses raw JSON exports from Bubble.io and decomposes their monolithic structure into a clean, normalized, and granular file system. It was built explicitly to help humans and AI coding agents (such as Google Deepmind Antigravity, Cursor, etc.) navigate and migrate the underlying data without needing to understand Bubble's proprietary, nested object structure.

## Core Features
- **Deterministic Portability**: Runs convert chaotic exports into highly standardized, predictable outputs.
- **Entity Granularity**: One file per entity type (Page UI vs Workflows vs Triggers).
- **Embedded API Inventories**: Automatically untangles plugin payloads, internal endpoint references, and identifies third-party systems the app relies on.
- **Smart "Gap" Audits**: Finds missing logic, orphaned element references, and logic that cannot easily be extracted dynamically.

---

## Getting Started

### 1. Requirements and Setup
You will need Python 3.10+ installed.

```bash
# Clone the repository
git clone https://github.com/christianbartens/parse-bubble-app-export.git
cd parse-bubble-app-export

# Create a virtual environment and install dependencies natively
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Procuring the Export
1. Inside your Bubble visual editor, click on **Settings > General**.
2. Click **Export Application**.
3. Bubble will email you or instantly download a `.json` (sometimes packaged as a `.zip`).
4. Place this export file into the `input/` directory of this repo. 

_Optional: If your application has a formal `swagger.json` or `openapi.json` definition for its API calls, place it in the `input/` folder alongside the Bubble export before parsing. The parser will automatically map API calls to defined paths._

### 3. Execution
Run the parser using the command line:

```bash
# General Parsing
./.venv/bin/python -m parser.cli --input input --output output

# Strict Mode (Will fail explicitly and exit if it detects critical migration blockers in the logic)
./.venv/bin/python -m parser.cli --input input --output output --strict
```

The tool clears the `output/` directory on every non-dry run to ensure its contents strictly match the final export.

---

## Output Architecture and Workflow

The parser structures the data into the target `--output` directory (e.g., `output/`). This directory is fully self-contained and portable; no paths are resolved outside of it.

For detailed specifics, look at the generated `output/README.md` after running the parser. At a high level, the payload separates cleanly between Application structural data and System metadata:

### AI Agent Workflow
To assist an AI coding agent with the app, point them directly at the **output directory**.
They should read the generated **`app_overview.md`**, **`app_counts.md`**, and **`README.md`** files within the output directory first to index the app semantics.

### Foundational Project Data
- `pages/`: Individual pages containing their DOM elements, reusables, workflows, and plugins.
- `reusables/`: Reusable Elements that act as components, complete with their workflows.
- `workflows/`: Standalone Backend Workflows and API Workflows.
- `data_types/`: Defines the schemas for all database Tables/Custom Types.
- `data_privacy/`: Security rules for the data types.
- `styles/` & `data_options/`: Central application styles and Option Sets.

### Extracted Integrations & Audits
- `plugins/` & `apis/`: Custom action types and extracted third-party API configurations.
- `follow_up/`: Highlighted missing references, unknown node shapes, or implementation blind spots that manual developers should analyze prior to migrating.

### System Artifacts
- `system/`: Contains technical metadata, ID maps, and manifest files tracking byte counts and original Bubble internal keys.

## Development and Testing

If you are modifying the parser, execute the test suite (59+ tests) via:
```bash
./.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```
