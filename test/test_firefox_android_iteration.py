"""Contract tests for the safe Firefox Android development runner."""
from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "firefox-android-iterate.sh"


class FirefoxAndroidIterationTests(unittest.TestCase):
    def _run(self, adb_output: str, *args: str, execute: bool = False):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            adb = tmp / "adb"
            adb.write_text(f"#!/bin/sh\ncat <<'EOF'\n{adb_output}EOF\n", encoding="utf-8")
            adb.chmod(0o755)
            web_ext = tmp / "web-ext"
            web_ext.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$WEB_EXT_ARGS\"\n"
                "while [ \"$1\" != --source-dir ]; do shift; done\n"
                "cp \"$2/manifest.json\" \"$WEB_EXT_ARGS.manifest\"\n",
                encoding="utf-8",
            )
            web_ext.chmod(0o755)
            env = dict(os.environ, ADB_BIN=str(adb), WEB_EXT_BIN=str(web_ext))
            if execute:
                env["WEB_EXT_ARGS"] = str(tmp / "args")
            else:
                env["WEB_EXT_ARGS"] = str(tmp / "unused")
            result = subprocess.run(
                [str(SCRIPT), *args], cwd=ROOT, env=env,
                capture_output=True, text=True,
            )
            captured = (tmp / "args").read_text(encoding="utf-8") if execute else ""
            if execute:
                manifest = json.loads((tmp / "args.manifest").read_text())
                self.assertNotIn("nativeMessaging", manifest["permissions"])
            return result, captured

    def test_dry_run_selects_the_only_ready_device(self):
        result, _ = self._run("List of devices attached\nphone-1\tdevice\n", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--target firefox-android", result.stdout)
        self.assertIn("--adb-device phone-1", result.stdout)

    def test_multiple_devices_fail_closed_without_selection(self):
        result, _ = self._run(
            "List of devices attached\na\tdevice\nb\tdevice\n", "--dry-run"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--adb-device", result.stderr)

    def test_execute_passes_android_target_and_stages_mobile_source(self):
        result, args = self._run(
            "List of devices attached\nphone-1\tdevice\n",
            "--firefox-apk", "org.mozilla.firefox_beta",
            "--allow-persistent-replacement", execute=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run\n", args)
        source = args.split("--source-dir\n", 1)[1].splitlines()[0]
        self.assertNotEqual(source, str(ROOT / "extension"))
        self.assertFalse(Path(source).exists(), "temporary source must be cleaned up")
        self.assertIn("--target\nfirefox-android\n", args)
        self.assertIn("--firefox-apk\norg.mozilla.firefox_beta\n", args)

    def test_execute_refuses_without_persistent_replacement_acknowledgement(self):
        result, _ = self._run(
            "List of devices attached\nphone-1\tdevice\n",
        )
        self.assertEqual(result.returncode, 3)
        self.assertIn("Refusing to start", result.stderr)
        self.assertIn("--allow-persistent-replacement", result.stderr)

    def test_runner_never_resolves_web_ext_with_npx(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("node_modules/.bin/web-ext", source)
        self.assertNotIn("npx --yes", source)


if __name__ == "__main__":
    unittest.main()


def test_android_stage_reloads_runtime_and_manifest_changes(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    from firefox_android import sync_source

    source = tmp_path / "extension"
    stage = tmp_path / "stage"
    source.mkdir()
    stage.mkdir()
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text())
    (source / "manifest.json").write_text(json.dumps(manifest))
    for name in ("background.js", "content.js", "sleeper.js"):
        (source / name).write_text("old")
    sync_source(source, stage)
    identity = (stage / "SOURCE_ID").read_bytes()
    unchanged_time = (stage / "content.js").stat().st_mtime_ns
    (source / "background.js").write_text("new")
    manifest["version"] = "9.0.0"
    (source / "manifest.json").write_text(json.dumps(manifest))
    (stage / "obsolete.js").write_text("obsolete")
    sync_source(source, stage)
    assert (stage / "background.js").read_text() == "new"
    assert (stage / "content.js").stat().st_mtime_ns == unchanged_time
    staged_manifest = json.loads((stage / "manifest.json").read_text())
    assert staged_manifest["version"] == "9.0.0"
    assert "nativeMessaging" not in staged_manifest["permissions"]
    assert "nativeMessaging" in json.loads((source / "manifest.json").read_text())["permissions"]
    assert (stage / "SOURCE_ID").read_bytes() != identity
    assert not (stage / "obsolete.js").exists()
