# Synthia AI Node (Python)

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Current run mode

The project currently provides Phase 1 onboarding modules and tests.
There is not yet a single production CLI entrypoint wired for full runtime startup.

## Validation

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py' -v
```
