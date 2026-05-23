# Unit Test Suite

This directory contains the consolidated unit test suite for the project.

Run all tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

The frontend utility tests are executed through `node --test` by
`tests/unit/frontend/test_frontend_unit_runner.py`, so the same `pytest tests`
command covers both Python backend units and pure JavaScript frontend helpers.

The tests are intentionally isolated from OpenAI, Supabase, Redis and Celery
workers. External integrations are replaced with fakes or monkeypatches.
