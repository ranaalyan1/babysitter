"""Validate + Repair stage tests: well-formedness checks and the full
JSON-healing catalog."""

import json

import pytest

from babysitter.repair import heal_json, repair_call
from babysitter.validate import (
    CODE_ARG_TOO_LARGE,
    CODE_BAD_JSON,
    CODE_BAD_PATH,
    CODE_MISSING_FIELD,
    CODE_PATH_ESCAPE,
    CODE_UNKNOWN_TOOL,
    CODE_WRONG_TYPE,
    validate_call,
)

ROOT = "/tmp/proj"  # project root for containment checks (no FS access needed)


def codes(result):
    return [i.code for i in result.issues]


# -- validate ---------------------------------------------------------------


def test_valid_call_passes():
    r = validate_call("write_file", {"path": "a.txt", "content": "hi"}, ROOT)
    assert r.ok and r.args == {"path": "a.txt", "content": "hi"}


def test_unknown_tool():
    r = validate_call("run_shell", "{}", ROOT)
    assert not r.ok and codes(r) == [CODE_UNKNOWN_TOOL]


def test_bad_json_reported_not_fixed_by_validate():
    r = validate_call("read_file", "{oops", ROOT)
    assert not r.ok and codes(r) == [CODE_BAD_JSON]
    assert r.args is None


def test_non_object_json_rejected():
    r = validate_call("read_file", "[1,2]", ROOT)
    assert not r.ok and codes(r) == [CODE_BAD_JSON]


def test_missing_field():
    r = validate_call("read_file", {}, ROOT)
    assert not r.ok and codes(r) == [CODE_MISSING_FIELD]


def test_wrong_type():
    r = validate_call("read_file", {"path": 123}, ROOT)
    assert not r.ok and codes(r) == [CODE_WRONG_TYPE]


def test_absolute_path_rejected():
    r = validate_call("read_file", {"path": "/etc/passwd"}, ROOT)
    assert not r.ok and codes(r) == [CODE_BAD_PATH]


def test_path_escape_rejected():
    r = validate_call("read_file", {"path": "../../etc/passwd"}, ROOT)
    assert not r.ok and codes(r) == [CODE_PATH_ESCAPE]


def test_dotdot_inside_root_allowed():
    r = validate_call("read_file", {"path": "sub/../a.txt"}, ROOT)
    assert r.ok


def test_oversize_args_rejected():
    r = validate_call("write_file", {"path": "a", "content": "x" * 300_000}, ROOT)
    assert not r.ok and CODE_ARG_TOO_LARGE in codes(r)


def test_custom_specs_protocol_mode():
    specs = {
        "get_weather": {
            "name": "get_weather",
            "description": "",
            "parameters": {
                "type": "object",
                "required": ["city"],
                "properties": {"city": {"type": "string"}},
            },
        }
    }
    ok = validate_call("get_weather", {"city": "Oslo"}, ROOT, specs=specs,
                       check_paths=False)
    assert ok.ok
    bad = validate_call("get_weather", {}, ROOT, specs=specs, check_paths=False)
    assert codes(bad) == [CODE_MISSING_FIELD]
    unknown = validate_call("read_file", {"path": "a"}, ROOT, specs=specs,
                            check_paths=False)
    assert codes(unknown) == [CODE_UNKNOWN_TOOL]


def test_check_paths_flag():
    specs = {
        "fetch": {
            "name": "fetch", "description": "",
            "parameters": {"type": "object", "required": ["path"],
                           "properties": {"path": {"type": "string"}}},
        }
    }
    strict = validate_call("fetch", {"path": "/abs"}, ROOT, specs=specs,
                           check_paths=True)
    assert codes(strict) == [CODE_BAD_PATH]
    lax = validate_call("fetch", {"path": "/abs"}, ROOT, specs=specs,
                        check_paths=False)
    assert lax.ok


# -- heal_json catalog --------------------------------------------------------


def test_heal_valid_json_is_noop():
    parsed, fixes = heal_json('{"path": "a"}')
    assert parsed == {"path": "a"} and fixes == []


def test_heal_fences():
    parsed, fixes = heal_json('```json\n{"path": "a"}\n```')
    assert parsed == {"path": "a"} and fixes == ["strip-fences"]


def test_heal_prose_around_object():
    parsed, fixes = heal_json('Sure! {"path": "a"} hope this helps')
    assert parsed == {"path": "a"} and FIX_EXTRACT in fixes


FIX_EXTRACT = "extract-object"


def test_heal_trailing_commas():
    parsed, fixes = heal_json('{"path": "a",}')
    assert parsed == {"path": "a"} and "drop-trailing-commas" in fixes


def test_heal_unquoted_keys():
    parsed, fixes = heal_json('{path: "a"}')
    assert parsed == {"path": "a"} and "quote-keys" in fixes


def test_heal_single_quotes():
    parsed, fixes = heal_json("{'path': 'a'}")
    assert parsed == {"path": "a"} and "single-to-double" in fixes


def test_heal_literals():
    parsed, fixes = heal_json('{"path": None, "x": True}')
    assert parsed == {"path": None, "x": True} and "fix-literals" in fixes


def test_heal_unclosed_brackets():
    parsed, fixes = heal_json('{"path": "a"')
    assert parsed == {"path": "a"} and "close-brackets" in fixes


def test_heal_combined_mess():
    parsed, fixes = heal_json("```\n{path: 'a',}\n```")
    assert parsed == {"path": "a"}
    assert "strip-fences" in fixes and "quote-keys" in fixes


def test_heal_hopeless_returns_none():
    parsed, _ = heal_json("just some prose without braces")
    assert parsed is None


# -- repair_call --------------------------------------------------------------


def test_repair_fixes_malformed_and_validates():
    r = repair_call("read_file", "{path: 'a',}", ROOT)
    assert r.ok and r.args == {"path": "a"}
    assert r.fixes  # named fixes for the trace


def test_repair_drops_extra_fields():
    r = repair_call("read_file", {"path": "a", "bogus": 1}, ROOT)
    assert r.ok and r.args == {"path": "a"}
    assert "drop-extra:bogus" in r.fixes


def test_repair_coerces_safe_types():
    r = repair_call("read_file", {"path": 123}, ROOT)
    assert r.ok and r.args == {"path": "123"}
    assert any(f.startswith("coerce:path") for f in r.fixes)


def test_repair_fills_schema_defaults():
    specs = {
        "greet": {
            "name": "greet", "description": "",
            "parameters": {"type": "object", "required": ["name", "punct"],
                           "properties": {"name": {"type": "string"},
                                          "punct": {"type": "string",
                                                    "default": "!"}}},
        }
    }
    r = repair_call("greet", {"name": "Al"}, ROOT, specs=specs)
    assert r.ok and r.args == {"name": "Al", "punct": "!"}
    assert "default:punct" in r.fixes


def test_repair_missing_without_default_fails():
    r = repair_call("read_file", {}, ROOT)
    assert not r.ok and "missing required field" in r.reason


def test_repair_never_guesses_paths():
    r = repair_call("read_file", {"path": "/etc/passwd"}, ROOT)
    assert not r.ok and "still invalid after repair" in r.reason
    r2 = repair_call("read_file", {"path": "../escape"}, ROOT)
    assert not r2.ok


def test_repair_unknown_tool_fails():
    r = repair_call("nuke", "{}", ROOT)
    assert not r.ok


def test_repair_accepts_dict_input():
    r = repair_call("write_file", {"path": "a", "content": 5}, ROOT)
    assert r.ok and r.args == {"path": "a", "content": "5"}


def test_repair_uncoercible_type_fails():
    r = repair_call("read_file", {"path": {"nested": True}}, ROOT)
    assert not r.ok
