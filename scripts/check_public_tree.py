#!/usr/bin/env python3
"""Reject maintainer-only files from Sleeper's publishable Git tree."""

from __future__ import annotations

import re
import subprocess
import os
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]

# Fail closed: adding a publishable file requires an explicit policy review.
PUBLIC_ALLOWLIST = {
    "plugins/claude/sleeper/skills/sleeper/references/setup.md",
    "plugins/claude/sleeper/skills/sleeper/references/network.md",
    "plugins/codex/sleeper/skills/sleeper/references/setup.md",
    "plugins/codex/sleeper/skills/sleeper/references/network.md",

    "plugins/codex/sleeper/assets/icon.svg",
    "plugins/claude/sleeper/assets/icon.svg",
    "test/browser_identity_test.js",
    "test/background_tabs_test.js",
    "test/background_network_test.js",
    "test/background_network_download_test.js",
    "test/background_waitxhr_test.js",
    "test/test_launch_gate.py",
    "test/background_page_hooks_test.js",
    "test/background_page_routing_test.js",
    "test/debugger_eval_test.js",
    "test/newtab_retry_test.js",
    "test/waittext_rendered_test.js",
    "test/goto_settle_test.js",
    ".github/FUNDING.yml",
    ".github/workflows/test.yml",
    ".github/workflows/release.yml",
    ".gitignore",
    "LICENSE",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "CHANGELOG.md",
    "package.json",
    "package-lock.json",
    "docs/i18n/README.zh-CN.md",
    "docs/i18n/README.ja.md",
    "docs/i18n/README.pt-BR.md",
    "docs/i18n/README.es.md",
    "docs/i18n/README.de.md",

    "docs/SPONSORS.md",
    "THIRD_PARTY_NOTICES.md",
    "extension/action-labels.js",
    "extension/api_host_policy.js",
    "assets/repository-hero.png",
    "assets/repository-social-preview.png",
    "extension/background.js",
    "extension/action-state.js",
    "extension/background_tabs.js",
    "extension/background_network.js",
    "extension/background_page_hooks.js",
    "extension/debugger_eval.js",
    "extension/daemon_endpoint.js",
    "extension/dynamic_code.js",
    "extension/mobile_onboarding.js",
    "extension/tailscale_setup.js",
    "extension/screenshot.js",
    "scripts/build-xpi.sh",
    "scripts/build-chromium.sh",
    "extension/content.js",
    "daemon/daemon.py",
    "daemon/__init__.py",
    "daemon/native_messaging_host.py",
    "docs/mcp-tools.json",
    "extension/icon-active.png",
    "extension/icon-active128.png",
    "extension/icon-active16.png",
    "extension/icon-active32.png",
    "extension/icon.png",
    "extension/icon128.png",
    "extension/icon16.png",
    "extension/icon32.png",
    "extension/icon.svg",
    "extension/icon-active.svg",
    "extension/icon48.png",
    "install.sh",
    "extension/manifest.json",
    "extension/manifest.chromium.json",
    "daemon/mcp_server.py",
    "packaging/sleeper.service",
    "extension/options.css",
    "extension/options.html",
    "extension/options.js",
    "extension/popup.css",
    "extension/popup.html",
    "extension/popup.js",
    "test/action_labels_test.js",
    "test/content_dialog_idle_test.js",
    "examples/recipes/chatgpt-delete-conversations.json",
    "examples/recipes/chatgpt-export-titles.json",
    "daemon/redaction.py",
    "pyproject.toml",
    "uv.lock",
    "examples/schemas/ig-profile.json",
    "examples/schemas/product-listing.json",
    "scripts/check_public_tree.py",
    "scripts/export-public.py",
    "scripts/install.py",
    "scripts/gen_mcp_tools.py",
    "scripts/build_packages.py",
    "scripts/sign-firefox.sh",
    "scripts/firefox-android-iterate.sh",
    "cli/adapter.py",
    "cli/recipe_cli.sh",
    "cli/sleeper",
    "cli/sleeper.py",
    "cli/tailscale_mobile.py",
    "cli/__init__.py",
    "install.ps1",
    "packaging/com.shy-tangerine.sleeper.plist",
    "extension/locators.js",
    "extension/activity.js",
    "extension/sleeper.js",
    "scripts/build_native_plugins.py",
    "scripts/install_plugins.py",
    "test/native_plugins_test.py",
    "test/install_plugins_test.py",
    "test/mobile_onboarding_test.js",
    "test/action_correctness_test.js",
    "test/action_log_test.js",
    "test/action_showcase_test.js",
    "test/android_background_test.js",
    "test/daemon_endpoint_test.js",
    "test/options_connection_test.js",
    "test/test_android_manifest.py",
    "test/test_firefox_android_iteration.py",
    "test/test_source_identity.py",
    "test/tailscale_setup_test.js",
    "test/fixtures/README.md",
    "test/fixtures/controlled-inputs.html",
    "test/test_tailscale_mobile.py",
    "test/test_uv_install.py",
    "plugins/claude/sleeper/.claude-plugin/plugin.json",
    "plugins/claude/sleeper/.mcp.json",
    "plugins/claude/sleeper/skills/sleeper/SKILL.md",
    "plugins/claude/.claude-plugin/marketplace.json",
    ".claude-plugin/marketplace.json",
    "plugins/codex/sleeper/.codex-plugin/plugin.json",
    "plugins/codex/sleeper/.mcp.json",
    "plugins/codex/sleeper/skills/sleeper/SKILL.md",
    ".agents/plugins/marketplace.json",
    "docs/OPENCLI-PARITY.md",
    "docs/installation.md",
    "docs/publication.md",
    "docs/firefox-signing.md",
    "docs/android.md",
    "docs/commands.md",
    "docs/agent-skill.md",
    "docs/comparison.md",
    "docs/benchmarks/matched-browser-interface.md",
    "benchmarks/README.md",
    "benchmarks/fixture/server.py",
    "benchmarks/run_matched_sleeper_chromium.py",
    "benchmarks/run_matched_opencli.py",
    "benchmarks/results/matched-browser-interface-samples.json",
    "benchmarks/token_measurement.py",
    "benchmarks/summarize_tokens.py",
    "benchmarks/run_matched_cdp.py",
    "benchmarks/run_matched_playwright_mcp.py",
    "benchmarks/results/cdp-matched-results.json",
    "test/test_token_measurement.py",
    "test/test_cli_json_helpers.py",
    "test/test_cli_observation_payloads.py",
    "benchmarks/results/matched-token-samples.json",
    "benchmarks/results/mcp-discovery-sample.json",
    "benchmarks/results/sleeper-mcp-matched-results.json",
    "benchmarks/results/playwright-mcp-token-results.json",
    "benchmarks/run_cli_protocol_capture.py",
    "benchmarks/run_opencli_protocol_capture.py",
    "benchmarks/opencli_fetch_capture.mjs",
    "benchmarks/results/opencli-cli-protocol-capture.json",
    "benchmarks/results/sleeper-cli-protocol-capture.json",
    "test/api_host_policy_test.js",
    "test/icon_state_test.js",
    "test/mock.py",
    "test/run.sh",
    "test/test_daemon_health.py",
    "test/test_native_messaging_host.py",
    "test/screenshot_transport_test.js",
    "test/screenshot_behavior_test.js",
    "test/focus_policy_test.js",
    "test/action_icon_timing_test.js",
    "test/test_installer_integrations.py",
    "test/activity_test.js",
    "test/test_cli_parity.py",
    "test/test_adapter.py",
    "test/locators_test.js",
    "test/locator_handlers_test.js",
    "test/test_cli_transport.py",
 "test/test_mcp_server.py",
    "test/test_daemon_routing.py",
    "test/test_daemon_timeouts.py",
    "test/test_docs.py",
    "test/test_installer.py",
    "test/test_cross_platform.py",
    "test/test_public_tree.py",
    "test/test_public_export.py",
    "test/test_redaction.py",
    "test/test_packaging.py",
    "test/validate_payloads.py",
    "skills/sleeper/SKILL.md",
    "skills/sleeper/references/setup.md",
    "skills/sleeper/references/network.md",
}

FORBIDDEN_EXACT = {
    ".mcp.json",
    ".repowise-workspace.yaml",
    "AGENTS.md",
    "AUDIT.md",
    "DESIGN.md",
    "EXTENSION-PLAN.md",
    "ZEN-BROWSER-FIELD-REPORT.md",
}

FORBIDDEN_PREFIXES = (
    ".codebase-memory/",
    ".repowise/",
    ".sieve/",
    "build/",
    "dist/",
    "research/",
    "wiki/",
)

FORBIDDEN_NAME_PREFIXES = ("HANDOFF-",)

# Runtime icons live under extension/. These names identify private design
# boards and intermediate/exported artwork. Keep them forbidden even if a
# future edit accidentally adds one to PUBLIC_ALLOWLIST.
FORBIDDEN_ASSET_PREFIXES = (
    "assets/brand-board-",
    "assets/addon-icon-",
)

# Private setup/client names are content leaks even when they occur in an
# otherwise publishable file. Keep this list deliberately small and explicit;
# reports contain paths only, never matching content. Parts are intentionally
# separate so the identifier does not appear in the policy source itself.
FORBIDDEN_PUBLIC_LITERAL_PARTS = (
    ("iron", "fox"),
    ("quiet", "-", "terracotta", "-", "sleeper"),
)
FORBIDDEN_PUBLIC_LITERALS = tuple("".join(parts) for parts in FORBIDDEN_PUBLIC_LITERAL_PARTS)
TAILSCALE_KEY_PATTERN = re.compile(
    r"\btskey-(?:auth|client|api|sc)-[A-Za-z0-9][A-Za-z0-9_-]{15,}\b",
    re.IGNORECASE,
)
TAILSCALE_ASSIGNED_SECRET_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:TAILSCALE_AUTHKEY|TAILSCALE_API_KEY|TS_AUTHKEY|TS_API_KEY)"
    r"\s*(?:=|:)\s*(?:[\"'](?P<quoted>[^\"']*)[\"']|(?P<bare>[^\s,;}]+))",
    re.IGNORECASE,
)
PLACEHOLDER_SECRET_VALUES = {
    "",
    "none",
    "null",
    "example",
    "example-key",
    "changeme",
    "your-key",
    "your-api-key",
    "placeholder",
    "replace-me",
    "redacted",
    "todo",
    "tbd",
}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".xml",
    ".yml",
    ".yaml",
}
TEXT_FILENAMES = {".gitignore", "CHANGELOG", "LICENSE"}


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in PLACEHOLDER_SECRET_VALUES:
        return True
    if (normalized.startswith("<") and normalized.endswith(">")) or (
        normalized.startswith("${") and normalized.endswith("}")
    ):
        return True
    return any(token in normalized for token in ("example", "placeholder", "changeme", "replace_me"))


def _contains_forbidden_content(text: str) -> bool:
    lowered = text.casefold()
    if any(literal.casefold() in lowered for literal in FORBIDDEN_PUBLIC_LITERALS):
        return True
    if TAILSCALE_KEY_PATTERN.search(text):
        return True
    for match in TAILSCALE_ASSIGNED_SECRET_PATTERN.finditer(text):
        value = match.group("quoted") if match.group("quoted") is not None else match.group("bare")
        if value is not None and len(value.strip()) >= 12 and not _looks_like_placeholder(value):
            return True
    return False


def content_violations(paths: list[str], root: Path = ROOT) -> list[str]:
    """Return paths whose reviewable text contains a forbidden literal."""
    blocked: set[str] = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path).as_posix()
        while path.startswith("./"):
            path = path[2:]
        name = PurePosixPath(path).name
        if PurePosixPath(path).suffix.lower() not in TEXT_SUFFIXES and name not in TEXT_FILENAMES:
            continue
        candidate = root.joinpath(*PurePosixPath(path).parts)
        try:
            payload = candidate.read_bytes()
        except (OSError, ValueError):
            continue
        # Avoid decoding binary assets. Text candidates containing a NUL are
        # treated as binary; invalid UTF-8 is likewise not reviewable text.
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _contains_forbidden_content(text):
            blocked.add(path)
    return sorted(blocked)


def dev_only_entries(root: Path = ROOT) -> tuple[str, ...]:
    """Return staging-only paths registered in ``dev-only.txt``.

    Entries are repo-relative paths; a trailing slash marks a directory and
    covers everything below it. A missing manifest means nothing is
    registered. Dev-only paths are exempt from the publishable allowlist but
    still go through content scanning.
    """
    try:
        text = (root / "dev-only.txt").read_text(encoding="utf-8")
    except OSError:
        return ()
    entries: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return tuple(entries)


def _is_dev_only(path: str, entries: tuple[str, ...]) -> bool:
    return any(
        path.startswith(entry) if entry.endswith("/") else path == entry
        for entry in entries
    )


def violations(paths: list[str], root: Path = ROOT) -> list[str]:
    """Return forbidden paths and forbidden text literals under ``root``."""
    dev_only = dev_only_entries(root)
    blocked: set[str] = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path).as_posix()
        while path.startswith("./"):
            path = path[2:]
        name = PurePosixPath(path).name
        publishable = path in PUBLIC_ALLOWLIST and not (
            path in FORBIDDEN_EXACT
            or path.startswith(FORBIDDEN_PREFIXES)
            or name.startswith(FORBIDDEN_NAME_PREFIXES)
            or any(path.startswith(prefix) for prefix in FORBIDDEN_ASSET_PREFIXES)
        )
        # A path is acceptable exactly two ways: reviewed-publishable, or
        # registered as staging-only in dev-only.txt (export strips it, the
        # launch gate enforces the strip, and content scanning below still
        # applies to it).
        if not publishable and not _is_dev_only(path, dev_only):
            blocked.add(path)
    blocked.update(content_violations(paths, root))
    return sorted(blocked)


def tracked_files() -> list[str]:
    """Return existing tracked and non-ignored untracked paths.

    The checker is also used against a dirty staging checkout. Including
    non-ignored untracked files keeps that mode consistent with
    ``scripts/export-public.py`` and prevents a new private file from being
    silently omitted until after a commit.
    """
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        top = ""
    if top != str(ROOT):
        ignored = {".git", ".venv", "__pycache__", ".pytest_cache", "release-candidate"}
        paths = []
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in ignored and not d.endswith(".egg-info")]
            paths.extend(os.path.relpath(os.path.join(base, name), ROOT) for name in files
                         if name not in {"SHA256SUMS", "VALIDATION.md", "sleeper-source-2.0.0.zip"})
        return sorted(paths)
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode("utf-8", errors="surrogateescape")
    untracked_output = subprocess.check_output(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=ROOT
    ).decode("utf-8", errors="surrogateescape")
    # Deleted paths are omitted so a cleanup can be checked before commit.
    # CI worktrees are clean and therefore cover the complete committed tree.
    return [
        path
        for path in sorted(set(output.split("\0") + untracked_output.split("\0")))
        if path and (ROOT / path).exists()
    ]


def main() -> int:
    blocked = violations(tracked_files())
    if blocked:
        print("PUBLIC TREE CHECK: FAILED", file=sys.stderr)
        print(
            "Unreviewed or maintainer-only paths are tracked in the publishable tree:",
            file=sys.stderr,
        )
        print("\n".join(f"- {path}" for path in blocked), file=sys.stderr)
        return 1
    print("PUBLIC TREE CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
