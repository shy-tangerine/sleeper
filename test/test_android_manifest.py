import json
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_firefox_manifest_declares_android_and_packages_endpoint_module(tmp_path):
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["browser_specific_settings"]["gecko_android"]["strict_min_version"] == "142.0"
    assert "daemon_endpoint.js" in manifest["background"]["scripts"]
    assert "dynamic_code.js" not in manifest["background"]["scripts"]
    assert "downloads" in manifest["permissions"]

    archive_path = tmp_path / "sleeper-firefox.zip"
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "build_packages.py"), "firefox",
        str(ROOT / "extension"), str(archive_path),
    ], check=True)
    with zipfile.ZipFile(archive_path) as archive:
        assert "daemon_endpoint.js" in archive.namelist()
        assert "dynamic_code.js" not in archive.namelist()


def test_extension_ui_has_mobile_viewports_and_touch_safe_styles():
    for name in ("options.html", "popup.html"):
        html = (ROOT / "extension" / name).read_text(encoding="utf-8")
        assert 'name="viewport"' in html
        assert "width=device-width" in html

    options_css = (ROOT / "extension" / "options.css").read_text(encoding="utf-8")
    popup_css = (ROOT / "extension" / "popup.css").read_text(encoding="utf-8")
    assert "min-width: 320px" not in options_css
    assert "@media (max-width: 640px)" in options_css
    assert "min-height: 44px" in options_css
    assert "overflow-x: hidden" in options_css
    assert "touch-action: manipulation" in options_css
    assert "min-height: 44px" in popup_css
    assert "overflow-x: hidden" in popup_css
    assert "touch-action: manipulation" in popup_css
