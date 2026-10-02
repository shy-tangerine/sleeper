import pytest

from cli.sleeper import parse_payload


@pytest.mark.parametrize("command", ["exec", "eval"])
@pytest.mark.parametrize("source", ["document.title", "false", "null", '"literal value"'])
def test_javascript_source_is_preserved_in_the_code_field(command, source):
    assert parse_payload([command, source])["args"] == {"code": source}


@pytest.mark.parametrize("source", ["false", "null", '"literal value"'])
def test_explicit_code_flag_preserves_javascript_source(source):
    assert parse_payload(["exec", "--code", source])["args"] == {"code": source}


@pytest.mark.parametrize("source", ["false", "null", "0", '"literal value"'])
def test_javascript_predicate_preserves_source(source):
    assert parse_payload(["wait_until", source])["args"] == {"predicate": source}


def test_object_predicate_remains_a_structured_condition():
    assert parse_payload(["wait_until", '{"selector":"h1","state":"visible"}'])["args"] == {
        "condition": {"selector": "h1", "state": "visible"},
    }


def test_documented_download_spelling_has_pattern_and_wait_budget():
    assert parse_payload(["wait_download", "report.txt", "--timeout", "750", "--tab", "fixture"]) == {
        "cmd": "waitDownload", "args": {"pattern": "report.txt", "timeout_ms": 750}, "tab": "fixture",
    }


@pytest.mark.parametrize("command", ["read", "read_all"])
@pytest.mark.parametrize("flags,expected", [
    (["--value"], {"what": "value"}),
    (["--html"], {"what": "html"}),
    (["--attr", "href"], {"what": "attr", "attr": "href"}),
])
def test_read_flags_select_the_requested_representation(command, flags, expected):
    assert parse_payload([command, "#search", *flags])["args"] == {"selector": "#search", **expected}
