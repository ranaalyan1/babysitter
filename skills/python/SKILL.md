---
name: python
description: Python coding conventions, idioms, and testing/formatting practices. Use when writing, reviewing, or debugging Python code, including scripts, services, and data pipelines.
license: MIT
compatibility: Requires Python 3.11+ and a terminal to run pytest/black/ruff.
allowed-tools: filesystem.read filesystem.write terminal.run
metadata:
  category: coding
  test0.tags: coding,python
---
# Python Skill

## When to use this skill
Use whenever writing, editing, or reviewing Python code — scripts,
services, CLIs, or data/bioinformatics pipelines.

## Instructions
1. Target Python 3.11+ unless the project specifies an older version.
2. Use type hints everywhere; prefer `dataclasses` or `pydantic` models
   for structured data over loose dicts.
3. Prefer `pathlib.Path` over `os.path` string manipulation.
4. Write tests with `pytest` under `tests/`, named `test_*.py`.
5. Format with `black`, lint with `ruff` before considering work done.
6. Declare dependencies in `pyproject.toml` (PEP 621) unless the project
   already uses `requirements.txt` — match existing convention.

## Common pitfalls
- Mutable default arguments (`def f(x=[])`) — use `None` + a guard instead.
- Bare `except:` clauses that swallow real errors — catch specific exceptions.
- Circular imports from overly deep package structures.
