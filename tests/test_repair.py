import json

import pytest

from aletheia.repair import ToolError, clean_call, declarations
from aletheia.tools import TOOLS
from conftest import call


def test_malformed_json_is_repaired(setup_runtime):
    config, _, project, _ = setup_runtime
    cleaned, notes, errors = clean_call(call(raw="{path: 'calc.py', content: '# fixed\\n',}"), declarations(TOOLS), project, config)
    assert json.loads(cleaned["function"]["arguments"])["path"] == "calc.py"
    assert notes and errors


def test_missing_fields_only_use_declared_defaults_and_types(setup_runtime):
    config, _, project, _ = setup_runtime
    schema = {"type": "object", "properties": {"count": {"type": "integer"}, "enabled": {"type": "boolean"},
              "mode": {"type": "string", "default": "safe"}}, "required": ["count", "enabled", "mode"]}
    cleaned, notes, errors = clean_call(call("example", raw='{"count":"3","enabled":"false"}'), {"example": schema}, project, config)
    assert json.loads(cleaned["function"]["arguments"]) == {"count": 3, "enabled": False, "mode": "safe"}
    assert len(notes) == 3 and errors


def test_required_content_never_invented(setup_runtime):
    config, _, project, _ = setup_runtime
    with pytest.raises(ToolError, match="required"):
        clean_call(call(args={"path": "calc.py"}), declarations(TOOLS), project, config)


def test_undeclared_tool_rejected(setup_runtime):
    config, _, project, _ = setup_runtime
    with pytest.raises(ToolError, match="undeclared"):
        clean_call(call("delete_everything"), declarations(TOOLS), project, config)


def test_additional_properties_rejected(setup_runtime):
    config, _, project, _ = setup_runtime
    with pytest.raises(ToolError):
        clean_call(call(args={"path": "calc.py", "content": "x", "unexpected": 1}), declarations(TOOLS), project, config)


def test_command_allowlist(setup_runtime):
    config, _, project, _ = setup_runtime
    schema = {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}
    with pytest.raises(ToolError, match="allowlist"):
        clean_call(call("shell", args={"command": "rm -rf /"}), {"shell": schema}, project, config)


def test_remote_schema_reference_forbidden():
    with pytest.raises(ToolError, match="local"):
        declarations([{"type": "function", "function": {"name": "bad", "parameters": {"$ref": "https://example.com/schema"}}}])


def test_repair_preserves_string_whitespace(setup_runtime):
    config, _, project, _ = setup_runtime
    cleaned, _, _ = clean_call(call(raw='{path: "calc.py", content: "  # important whitespace\\n",}'), declarations(TOOLS), project, config)
    assert json.loads(cleaned["function"]["arguments"])["content"] == "  # important whitespace\n"
