"""v0.1 minimal toolset: the only tools a supervised agent may call.

Three file tools, all paths relative to the project root. Deliberately no
shell tool in v0.1: verification commands come from Babysitter's own
trusted config (babysitter.json), never from the model. If the model
needs a command run, it cannot — that is a scope boundary, not an
oversight (see docs/ARCHITECTURE.md).

Schemas use the OpenAI function-calling shape so they can be passed to
any OpenAI-compatible provider verbatim.
"""

from __future__ import annotations

#: Refuse argument payloads larger than this (DoS guard + runaway-model guard).
MAX_ARGS_BYTES = 256 * 1024

READ_FILE = {
    "name": "read_file",
    "description": "Read a text file from the project. Path is relative to the project root.",
    "parameters": {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {"path": {"type": "string", "description": "Relative file path."}},
    },
}

WRITE_FILE = {
    "name": "write_file",
    "description": "Create or overwrite a text file in the project. Parent directories are created. Path is relative to the project root.",
    "parameters": {
        "type": "object",
        "required": ["path", "content"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "content": {"type": "string", "description": "Full file content."},
        },
    },
}

EDIT_FILE = {
    "name": "edit_file",
    "description": "Replace one occurrence of old_text with new_text in a project file. Fails if old_text is absent or ambiguous. Paths are relative to the project root.",
    "parameters": {
        "type": "object",
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "description": "Relative file path."},
            "old_text": {"type": "string", "description": "Exact text to find."},
            "new_text": {"type": "string", "description": "Replacement text."},
        },
    },
}

TOOLS: dict[str, dict] = {
    "read_file": READ_FILE,
    "write_file": WRITE_FILE,
    "edit_file": EDIT_FILE,
}


def tool_spec(name: str) -> dict | None:
    """Return the OpenAI-shaped spec for a tool, or None if unknown."""
    return TOOLS.get(name)


def all_specs() -> list[dict]:
    """All tool specs in OpenAI ``tools`` item shape."""
    return [
        {"type": "function", "function": spec} for spec in TOOLS.values()
    ]


def anthropic_specs() -> list[dict]:
    """All tool specs in Anthropic Messages ``tools`` shape."""
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "input_schema": spec["parameters"],
        }
        for spec in TOOLS.values()
    ]
