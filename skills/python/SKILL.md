---
name: python
version: 1.0.0
description: Python coding conventions, idioms, and best practices
tags: [coding, python]
requiredTools: [filesystem.read, filesystem.write, terminal.run]
---
# Python Skill

- Target Python 3.11+ unless the project specifies otherwise.
- Use type hints and `dataclasses`/`pydantic` for structured data.
- Prefer `pathlib` over `os.path`.
- Use `pytest` for tests; place them under `tests/`.
- Format with `black`, lint with `ruff`.
- Manage dependencies with `pyproject.toml` (PEP 621) unless told otherwise.
