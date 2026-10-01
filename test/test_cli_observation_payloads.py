import pytest

from cli.sleeper import parse_payload


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
