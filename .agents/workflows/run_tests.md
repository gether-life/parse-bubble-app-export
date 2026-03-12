---
description: How to run the project tests
---

# Run Tests Workflow

Execute the full suite of unit tests to verify parser logic.

1. **Activate Environment**
   ```bash
   source .venv/bin/activate
   ```

2. **Run Unittest**
   // turbo
   ```bash
   ./.venv/bin/python -m unittest discover -s tests -p "test_*.py"
   ```

3. **Check Coverage (Optional)**
   If coverage tool is installed:
   ```bash
   coverage run -m unittest discover -s tests
   coverage report
   ```
