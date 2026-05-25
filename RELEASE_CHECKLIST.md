# Release Checklist — Labyrinth-OS Sentinel-Core

Run through this before every public push.

---

## Steps

```
[ ] 1. Fresh clone or unzip into a clean directory
[ ] 2. Create a virtual environment
        python -m venv .venv
[ ] 3. Activate it
        source .venv/bin/activate     (Linux/Mac)
        .venv\Scripts\activate        (Windows)
[ ] 4. Install dependencies
        python -m pip install -r requirements.txt
[ ] 5. Run the full test suite
        python run_all.py
[ ] 6. Run the runtime self-test
        python sentinel_core.py
[ ] 7. Confirm zero test failures
[ ] 8. Confirm README test count badge matches run_all.py output
[ ] 9. Confirm PRODUCTION_BOUNDARY.md accurately describes what runs
[  ] 10. Confirm no stale journal references are required to understand the repo
[ ] 11. Confirm .gitignore covers: __pycache__, .pytest_cache, .venv,
        *.pyc, generated receipts
```

---

## Pass Criteria

- `run_all.py` exits with zero failures
- `python sentinel_core.py` completes without exceptions
- README badge matches actual test output
- PRODUCTION_BOUNDARY.md matches actual capability
- No absolute safety claims anywhere in public-facing docs

---

*@LabyrinthCoder — sole authority on releases*
