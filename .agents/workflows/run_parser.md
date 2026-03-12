---
description: How to run the bubble export parser
---

# Run Parser Workflow

To parse a Bubble export, follow these steps:

1. **Place Input**
   Ensure your `.json` or `.zip` export is in the `input/` directory.

2. **Run the Command**
   // turbo
   ```bash
   ./.venv/bin/python -m parser.cli --input input --output output
   ```

3. **Check Results**
   Inspect `output/system/manifest.json` or `output/README.md` to see the parsed artifacts.

4. **Strict Mode (Optional)**
   To fail on any blocker gaps:
   ```bash
   ./.venv/bin/python -m parser.cli --input input --output output --strict
   ```
