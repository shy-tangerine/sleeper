import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args, profile=None):
    env = os.environ.copy()
    env["SLEEPER_DRY_RUN"] = "1"
    if profile:
        env["SLEEPER_PROFILE"] = profile
    out = subprocess.check_output([str(ROOT / "cli" / "sleeper"), *args], cwd=ROOT, env=env, text=True)
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
