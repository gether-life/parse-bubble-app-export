---
description: How to setup the development environment
---

# Setup Workflow

Follow these steps to prepare the repository for development or usage.

1. **Create Virtual Environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install Dependencies**
   // turbo
   ```bash
   python3 -m pip install -e .
   ```

3. **Verify Installation**
   // turbo
   ```bash
   python3 -m parser.cli --help
   ```
