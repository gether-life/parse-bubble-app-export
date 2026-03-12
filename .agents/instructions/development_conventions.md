# Development Conventions

## Python Environment
To prevent environment drift and unwanted IDE warnings (like "Select Python Interpreter"), all agents MUST use the local virtual environment for all background and terminal tasks.

### Mandated Paths
- **Python Executable**: `./.venv/bin/python`
- **Pip**: `./.venv/bin/pip`

### Usage Patterns
When running scripts, tests, or the CLI, always use the explicit path to the venv binary.
- **Example (CLI)**: `./.venv/bin/python -m parser.cli --help`
- **Example (Tests)**: `./.venv/bin/python -m unittest discover ...`

## Project Layout
- **Flat Layout**: The core package is located at `./parser/`. 
- **Package Name**: The package name is `parser`.

## Linter and IDE Settings
- **Exclusions**: The `input/` and `output/` directories are very large and must remain excluded from linter indexing in `.vscode/settings.json`.
- **Extra Paths**: The project root `${workspaceFolder}` should be included in `extraPaths` to ensure correct import resolution.
