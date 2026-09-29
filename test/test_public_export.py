#!/usr/bin/env python3
"""Regression tests for the history-free public source exporter."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "scripts" / "export-public.py"
SPEC = importlib.util.spec_from_file_location("export_public", EXPORTER)
assert SPEC and SPEC.loader
export_public = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_public)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class PublicExportContract(unittest.TestCase):
    def make_repo(self, root: Path, *, private: bool = False) -> None:
        git(root, "init", "--initial-branch=main")
        (root / ".gitignore").write_text("wiki/\n.repowise/\nbuild/\n", encoding="utf-8")
        (root / "README.md").write_text("public candidate\n", encoding="utf-8")
        (root / "scripts").mkdir()
        shutil.copy(ROOT / "scripts/check_public_tree.py", root / "scripts/check_public_tree.py")
        if private:
            (root / "internal-notes.md").write_text("do not export\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")

    def run_export(self, source: Path, destination: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(EXPORTER), str(destination), "--source-root", str(source), *extra],
            text=True,
            capture_output=True,
        )

    def test_export_has_no_history_and_omits_ignored_state(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            source.mkdir()
            self.make_repo(source)
            (source / "wiki").mkdir()
            (source / "wiki" / "private.md").write_text("private\n", encoding="utf-8")
            (source / ".repowise").mkdir()
            (source / ".repowise" / "state.json").write_text("private\n", encoding="utf-8")
            (source / "build").mkdir()
            (source / "build" / "sleeper.xpi").write_bytes(b"private artifact")
            result = self.run_export(source, destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((destination / "README.md").is_file())
            self.assertFalse((destination / ".git").exists())
            self.assertFalse((destination / "wiki").exists())
            self.assertFalse((destination / ".repowise").exists())
            self.assertFalse((destination / "build").exists())

    def test_export_rejects_unreviewed_tracked_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            source.mkdir()
            self.make_repo(source)
            (source / "internal-notes.md").write_text("private\n", encoding="utf-8")
            result = self.run_export(source, destination)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("internal-notes.md", result.stderr)
            self.assertFalse(destination.exists())

    def test_export_requires_new_destination_outside_checkout(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            source.mkdir()
            self.make_repo(source)
            inside = source / "candidate"
            result = self.run_export(source, inside)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the source checkout", result.stderr)

    def test_dry_run_does_not_create_destination(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            source.mkdir()
            self.make_repo(source)
            result = self.run_export(source, destination, "--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("README.md", result.stdout)
            self.assertFalse(destination.exists())

    def test_export_fails_if_source_identity_changes_before_open(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work) / "root"
            source = root / "source.txt"
            output_root_path = Path(work) / "output"
            output = output_root_path / "source.txt"
            outside = Path(work) / "outside.txt"
            root.mkdir()
            output_root_path.mkdir()
            source.write_text("public\n", encoding="utf-8")
            outside.write_text("private\n", encoding="utf-8")
            original_open = os.open

            def replace_then_open(path, flags, *args, **kwargs):
                if path == "source.txt":
                    source.unlink()
                    source.symlink_to(outside)
                return original_open(path, flags, *args, **kwargs)

            root_descriptor = export_public._open_root(root)
            output_root = export_public._open_root(output_root_path)
            try:
                with patch.object(export_public.os, "open", side_effect=replace_then_open):
                    with self.assertRaises(export_public.ExportError):
                        export_public._copy_checked(root_descriptor, output_root, "source.txt")
            finally:
                os.close(output_root)
                os.close(root_descriptor)
            self.assertFalse(output.exists())

    def test_export_fails_if_parent_is_replaced_with_symlink(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work) / "root"
            parent = root / "nested"
            outside = Path(work) / "outside"
            output_root_path = Path(work) / "output"
            output = output_root_path / "nested/source.txt"
            parent.mkdir(parents=True)
            outside.mkdir()
            output_root_path.mkdir()
            (parent / "source.txt").write_text("public\n", encoding="utf-8")
            (outside / "source.txt").write_text("private\n", encoding="utf-8")
            original_open = os.open

            def replace_then_open(path, flags, *args, **kwargs):
                if path == "nested":
                    parent.rename(root / "original")
                    parent.symlink_to(outside, target_is_directory=True)
                return original_open(path, flags, *args, **kwargs)

            root_descriptor = export_public._open_root(root)
            output_root = export_public._open_root(output_root_path)
            try:
                with patch.object(export_public.os, "open", side_effect=replace_then_open):
                    with self.assertRaises(export_public.ExportError):
                        export_public._copy_checked(root_descriptor, output_root, "nested/source.txt")
            finally:
                os.close(output_root)
                os.close(root_descriptor)
            self.assertFalse(output.exists())

    def test_export_fails_if_repository_root_is_replaced(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            replacement = Path(work) / "replacement"
            source.mkdir()
            replacement.mkdir()
            self.make_repo(source)
            self.make_repo(replacement)
            original_candidates = export_public.candidate_paths

            def replace_after_enumeration(root):
                paths = original_candidates(root)
                source.rename(Path(work) / "original")
                replacement.rename(source)
                return paths

            with patch.object(export_public, "candidate_paths", side_effect=replace_after_enumeration):
                with self.assertRaisesRegex(export_public.ExportError, "source root changed"):
                    export_public.export_tree(source, destination)
            self.assertFalse(destination.exists())

    def test_export_fails_if_destination_parent_is_replaced(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            parent = Path(work) / "publish"
            destination = parent / "candidate"
            source.mkdir()
            parent.mkdir()
            self.make_repo(source)
            original_candidates = export_public.candidate_paths

            def replace_after_enumeration(root):
                paths = original_candidates(root)
                parent.rename(Path(work) / "original-publish")
                parent.mkdir()
                return paths

            with patch.object(export_public, "candidate_paths", side_effect=replace_after_enumeration):
                with self.assertRaisesRegex(export_public.ExportError, "destination parent changed"):
                    export_public.export_tree(source, destination)
            self.assertFalse(destination.exists())

    def test_export_never_clobbers_destination_created_during_copy(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            source.mkdir()
            self.make_repo(source)
            original_copy = export_public._copy_checked
            appeared = False

            def create_destination(*args):
                nonlocal appeared
                original_copy(*args)
                if not appeared:
                    destination.mkdir()
                    (destination / "owner.txt").write_text("keep\n", encoding="utf-8")
                    appeared = True

            with patch.object(export_public, "_copy_checked", side_effect=create_destination):
                with self.assertRaisesRegex(export_public.ExportError, "destination appeared"):
                    export_public.export_tree(source, destination)
            self.assertEqual((destination / "owner.txt").read_text(encoding="utf-8"), "keep\n")

    def test_checker_accepts_pristine_history_free_export(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            destination = Path(work) / "candidate"
            source.mkdir()
            self.make_repo(source)
            result = self.run_export(source, destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            checked = subprocess.run(
                ["python3", str(destination / "scripts/check_public_tree.py")],
                cwd=destination,
                text=True,
                capture_output=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("PUBLIC TREE CHECK: PASS", checked.stdout)
            self.assertNotIn("fatal: not a git repository", checked.stderr)


if __name__ == "__main__":
    unittest.main()
