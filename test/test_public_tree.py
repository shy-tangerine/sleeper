#!/usr/bin/env python3
"""Contract tests for the public-tree publication boundary."""

from __future__ import annotations

import sys
import os
import unittest
import tempfile
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_public_tree import content_violations, violations  # noqa: E402


class PublicTreeContract(unittest.TestCase):
    def test_checker_scans_source_tree_without_git(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / "README.md").write_text("ok\n")
            (root / "private.txt").write_text("should fail\n")
            result = subprocess.run(["python3", str(root / "scripts/check_public_tree.py")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("private.txt", result.stderr)
            self.assertNotIn("fatal: not a git repository", result.stderr)

    def test_checker_rejects_build_artifacts_without_git(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / "README.md").write_text("public candidate\n")
            (root / "build").mkdir()
            (root / "build/sleeper.xpi").write_bytes(b"private artifact")
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("build/sleeper.xpi", result.stderr)
            self.assertNotIn("fatal: not a git repository", result.stderr)

    def test_checker_rejects_private_state_in_nested_git_tree(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / ".repowise").mkdir()
            (root / ".repowise/state.json").write_text("private")
            (root / "nested").mkdir()
            (root / "nested/.git").mkdir()
            result = subprocess.run(["python3", str(root / "scripts/check_public_tree.py")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(".repowise/state.json", result.stderr)

    def test_checker_scans_nonignored_untracked_files(self):
        """A dirty staging tree must not bypass the publication boundary."""
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / "README.md").write_text("ok\n")
            subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "README.md", "scripts/check_public_tree.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            (root / "internal-notes.md").write_text("should fail\n")
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("internal-notes.md", result.stderr)

    def test_checker_rejects_forbidden_setup_identifier_in_text(self):
        """Tracked and untracked publishable text must not expose private clients."""
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            private_client = "".join(("iRoN", "fOx"))
            (root / "scripts").mkdir()
            (root / "docs").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / "README.md").write_text(f"Setup was tested in {private_client}.\n")
            subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "README.md", "scripts/check_public_tree.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            # This is allowlisted by path, so only the content policy can catch it.
            (root / "docs/android.md").write_text(f"The phone uses {private_client.upper()} during setup.\n")
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("README.md", result.stderr)
            self.assertIn("docs/android.md", result.stderr)
            self.assertNotIn(private_client.casefold(), result.stderr.casefold())

    def test_content_scan_skips_binary_assets(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            asset = root / "assets/repository-hero.png"
            asset.parent.mkdir()
            asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join((b"IRON", b"FOX")) + b"\0binary")
            self.assertEqual(
                content_violations(["assets/repository-hero.png"], root),
                [],
            )

    def test_checker_rejects_tailscale_key_formats_and_assigned_secrets(self):
        """Credential-shaped keys and assigned values are never publishable."""
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            (root / "docs").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            key_prefix = "-".join(("tskey", "auth"))
            synthetic_key = f"{key_prefix}-" + ("Ab3" * 8)
            variable_name = "_".join(("TAILSCALE", "AUTHKEY"))
            (root / "README.md").write_text(f"Key: {synthetic_key}\n")
            subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "README.md", "scripts/check_public_tree.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            # This path is allowlisted, so the content policy must catch the assignment.
            assigned = "Zx9" * 8
            (root / "docs/android.md").write_text(f'{variable_name} = "{assigned}"\n')
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("README.md", result.stderr)
            self.assertIn("docs/android.md", result.stderr)
            self.assertNotIn(synthetic_key, result.stderr)
            self.assertNotIn(assigned, result.stderr)

    def test_checker_rejects_private_staging_repository_identifier(self):
        """Publishable text must not link back to the private staging repository."""
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            private_repo = "".join(("quiet", "-", "terracotta", "-", "sleeper"))
            (root / "scripts").mkdir()
            (root / "docs").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            (root / "README.md").write_text(f"Staging: {private_repo}.\n")
            subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "README.md", "scripts/check_public_tree.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            (root / "docs/commands.md").write_text(f"See {private_repo}.\n")
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("README.md", result.stderr)
            self.assertIn("docs/commands.md", result.stderr)
            self.assertNotIn(private_repo, result.stderr)

    def test_checker_allows_variable_names_without_assigned_values(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "scripts").mkdir()
            (root / "docs").mkdir()
            shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
            variable_names = " and ".join(
                "_".join(parts)
                for parts in (("TAILSCALE", "AUTHKEY"), ("TAILSCALE", "API", "KEY"), ("TS", "AUTHKEY"), ("TS", "API", "KEY"))
            )
            (root / "README.md").write_text(f"Supported variables: {variable_names}\n")
            subprocess.run(["git", "init", "--initial-branch=main"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "add", "README.md", "scripts/check_public_tree.py"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                ["python3", str(root / "scripts/check_public_tree.py")],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_maintainer_only_paths(self):
        self.assertEqual(
            violations(
                [
                    "README.md",
                    "wiki/kanban/Sleeper.md",
                    "research/notes.md",
                    ".repowise/state.json",
                    ".codebase-memory/graph.db.zst",
                    "build/.buildnum",
                    "build/sleeper.xpi",
                    "AUDIT.md",
                    "HANDOFF-CLI-BUG.md",
                    "docs/HANDOFF-release.md",
                    "internal-notes.md",
                ]
            ),
            [
                ".codebase-memory/graph.db.zst",
                ".repowise/state.json",
                "AUDIT.md",
                "HANDOFF-CLI-BUG.md",
                    "build/.buildnum",
                    "build/sleeper.xpi",
                "docs/HANDOFF-release.md",
                "internal-notes.md",
                "research/notes.md",
                "wiki/kanban/Sleeper.md",
            ],
        )

    def test_checker_allows_registered_dev_only_paths(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "dev-only.txt").write_text("AGENTS.md\ninternal/\n")
            self.assertEqual(
                violations(["README.md", "AGENTS.md", "internal/notes.md", "secret.txt"], root=root),
                ["secret.txt"],
            )

    def test_rejects_orphaned_internal_brand_assets(self):
        """Internal boards and source/export assets must never be allowlisted."""
        self.assertEqual(
            violations(
                [
                    "assets/brand-board-01.png",
                    "assets/addon-icon-active.png",
                    "assets/addon-icon-inactive.png",
                    "assets/addon-icon-master.png",
                ]
            ),
            [
                "assets/addon-icon-active.png",
                "assets/addon-icon-inactive.png",
                "assets/addon-icon-master.png",
                "assets/brand-board-01.png",
            ],
        )

    def test_allows_repository_presentation_assets(self):
        self.assertEqual(
            violations(
                [
                    "assets/repository-hero.png",
                    "assets/repository-social-preview.png",
                ]
            ),
            [],
        )

    def test_allows_public_product_and_test_files(self):
        self.assertEqual(
            violations(
                [
                    ".github/workflows/test.yml",
                    "PRIVACY.md",
                    "README.md",
                    "SECURITY.md",
                    "docs/publication.md",
                    "extension/action-labels.js",
                    "extension/background.js",
                    "extension/background_tabs.js",
                    "extension/action-state.js",
                    "extension/background_network.js",
                    "extension/background_page_hooks.js",
                    "extension/daemon_endpoint.js",
                    "extension/dynamic_code.js",
                    "extension/icon48.png",
                    "extension/mobile_onboarding.js",
                    "extension/tailscale_setup.js",
                    "test/action_correctness_test.js",
                    "test/action_log_test.js",
                    "test/action_showcase_test.js",
                    "test/android_background_test.js",
                    "test/daemon_endpoint_test.js",
                    "test/mobile_onboarding_test.js",
                    "test/options_connection_test.js",
                    "test/test_android_manifest.py",
                    "test/tailscale_setup_test.js",
                    "test/test_tailscale_mobile.py",
                    "scripts/export-public.py",
                    "test/test_public_tree.py",
                    "test/test_public_export.py",
                ]
            ),
            [],
        )


class BrowserModuleContractTests(unittest.TestCase):
    def test_browser_modules_and_screenshot_permissions(self):
        import json
        for name in ("extension/manifest.json", "extension/manifest.chromium.json"):
            manifest = json.loads((ROOT / name).read_text())
            if manifest["manifest_version"] == 3:
                self.assertNotIn("<all_urls>", manifest["permissions"])
                self.assertEqual(manifest["host_permissions"], ["http://*/*", "https://*/*"])
            else:
                self.assertIn("<all_urls>", manifest["permissions"])
            for content in manifest["content_scripts"]:
                scripts = content["js"]
                self.assertLess(scripts.index("locators.js"), scripts.index("sleeper.js"))
                for script in scripts:
                    self.assertTrue((ROOT / "extension" / script).is_file(), script)
        firefox = json.loads((ROOT / "extension" / "manifest.json").read_text())
        background = firefox["background"]["scripts"]
        self.assertLess(background.index("screenshot.js"), background.index("background.js"))
        self.assertLess(background.index("background_tabs.js"), background.index("background.js"))
        self.assertLess(background.index("action-state.js"), background.index("background.js"))
        self.assertLess(background.index("background_network.js"), background.index("background.js"))
        self.assertLess(background.index("background_page_hooks.js"), background.index("background.js"))
        self.assertLess(background.index("mobile_onboarding.js"), background.index("background.js"))
        self.assertLess(background.index("tailscale_setup.js"), background.index("background.js"))


if __name__ == "__main__":
    unittest.main()

class FirefoxSigningContractTests(unittest.TestCase):
    def test_signing_script_fails_closed_without_amo_credentials(self):
        env = {"PATH": os.environ.get("PATH", "")}
        result = subprocess.run(
            [str(ROOT / "scripts/sign-firefox.sh")], cwd=ROOT, env=env,
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AMO_JWT_ISSUER", result.stderr)

    def test_release_workflow_publishes_only_signed_firefox_xpi(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        signing_script = (ROOT / "scripts/sign-firefox.sh").read_text()
        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("git merge-base --is-ancestor", workflow)
        self.assertIn("npm ci --ignore-scripts --no-audit --no-fund", workflow)
        self.assertIn("tag_name: ${{ inputs.tag }}", workflow)
        self.assertIn("Sign Firefox package with AMO", workflow)
        self.assertIn("AMO_JWT_ISSUER", workflow)
        self.assertIn("build/sleeper-firefox.xpi", workflow)
        self.assertNotIn("            build/sleeper.xpi\n", workflow)
        self.assertIn("node_modules/.bin/web-ext", signing_script)
        self.assertNotIn("npx --yes", signing_script)
