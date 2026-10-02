import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args, profile=None, python_cli=False):
    env = os.environ.copy()
    env["SLEEPER_DRY_RUN"] = "1"
    if profile:
        env["SLEEPER_PROFILE"] = profile
    program = [sys.executable, "-m", "cli.sleeper"] if python_cli else [str(ROOT / "cli" / "sleeper")]
    out = subprocess.check_output([*program, *args], cwd=ROOT, env=env, text=True)
    return json.loads(out)


def test_semantic_writes_and_profile():
    click = run("click", "--role", "button", "--name", "Next", profile="qa")
    assert click["args"]["role"] == "button"
    assert click["args"]["name"] == "Next"
    assert click["profile"] == "qa"
    typed = run("type", "--role", "textbox", "--name", "Search", "abc", "--clear")
    assert typed["args"]["text"] == "abc"
    assert typed["args"]["clear"] is True
    selected = run("select", "--role", "combobox", "--name", "Sort", "relevance")
    assert selected["cmd"] == "selectOption"
    filled = run("fill_form", '{"q":"abc"}', "--role", "form", "--name", "Search")
    assert filled["args"]["fields"] == {"q": "abc"}
    dragged = run("drag", "--source-role", "button", "--source-name", "Card", "--target-role", "region", "--target-name", "Dropzone")
    assert dragged["args"]["source_role"] == "button"
    assert dragged["args"]["target_name"] == "Dropzone"
    assert run("state", profile="qa")["profile"] == "qa"


def test_observation_commands():
    shot = run("shot", "--full-page", "--annotate", "--width", "1200")
    assert shot["args"] == {"full_page": True, "annotate": True, "width": 1200}
    download = run("wait", "download", "report.pdf", "--timeout", "250")
    assert download["cmd"] == "waitDownload"
    assert download["args"]["pattern"] == "report.pdf"


def test_early_shot_command_forwards_profile():
    shot = run("shot", "--full-page", profile="qa")
    assert shot["profile"] == "qa"


def test_stable_tab_selectors_survive_cli_parsing():
    for python_cli in (False, True):
        for command in (("goto", "https://example.test"), ("read", "h1"), ("shot",)):
            payload = run(*command, "--tab", "id:328", python_cli=python_cli)
            assert payload.get("tab", payload["args"].get("tab")) == "id:328"
        for command in ("close", "select"):
            assert run("tab", command, "id:328", python_cli=python_cli)["args"]["target"] == "id:328"
