"""Keep published examples and MCP schema documentation executable and current."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAGING_ONLY_LINKS = {'CHANGELOG.md'}
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "daemon"))
import mcp_server
from scripts.check_public_tree import dev_only_entries


class DocumentationContract(unittest.TestCase):
    def test_mcp_inventory_matches_advertised_schemas(self):
        self.assertEqual(json.loads((ROOT / 'docs/mcp-tools.json').read_text()), mcp_server.TOOLS)

    def test_commands_cli_examples(self):
        commands_doc = ROOT / 'docs' / 'commands.md'
        block = commands_doc.read_text().split('<!-- cli-contract:start -->')[1].split('<!-- cli-contract:end -->')[0]
        commands = [shlex.split(line) for line in block.splitlines() if line.startswith('sleeper ')]
        expected = [
            ('sessions', {}),
            ('state', {}), ('tabs', {}),
            ('goto', {'url': 'https://example.com'}),
            ('find', {'selector': 'h1', 'limit': 5}),
            ('find', {'role': 'button', 'name': 'Save', 'limit': 50}),
            ('click', {'selector': '@sleeper-1'}),
            ('type', {'selector': 'input[name=q]', 'text': 'example query', 'clear': True}),
            ('read', {'selector': 'h1'}), ('readAll', {'selector': '.result'}),
            ('waitFor', {'selector': '.loaded', 'timeout': 15000}),
            ('extract', {'map': {'title': 'h1', 'items': '.result'}}),
            ('snapshot', {}), ('newtab', {'url': 'https://example.com'}),
            ('selecttab', {'target': '0'}), ('closetab', {'target': '0'}),
            ('waitDownload', {'pattern': 'report.csv', 'timeout_ms': 15000}),
            ('network', {'since': 60}), ('api', {'url': '/api/example', 'method': 'GET'}),
            ('shot', {'full_page': True, 'annotate': True, 'width': 1280, 'height': 800}),
        ]
        self.assertEqual(len(commands), len(expected))
        with tempfile.TemporaryDirectory() as work:
            env = dict(os.environ, SLEEPER_DRY_RUN='1', SLEEPER_SESSION_FILE=str(Path(work) / 'session'))
            env.pop('SLEEPER_PROFILE', None)
            for argv, (cmd, args) in zip(commands, expected):
                with self.subTest(example=shlex.join(argv)):
                    result = subprocess.run([str(ROOT / 'cli' / 'sleeper'), *argv[1:]], cwd=work,
                                            env=env, check=True, capture_output=True, text=True)
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload['cmd'], cmd)
                    for key, value in args.items():
                        self.assertEqual(payload.get('args', {}).get(key), value, key)

    def test_documentation_local_links_exist(self):
        documents = [ROOT / 'README.md', *(ROOT / 'docs').rglob('*.md')]
        if (ROOT / 'CHANGELOG.md').is_file():
            documents.insert(1, ROOT / 'CHANGELOG.md')
        for document in documents:
            for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
                if '://' not in target and not target.startswith('#'):
                    path = (document.parent / target.split('#')[0]).resolve()
                    if not path.is_file():
                        try:
                            relative = path.relative_to(ROOT).as_posix()
                        except ValueError:
                            relative = ''
                        if relative in STAGING_ONLY_LINKS or relative in dev_only_entries(ROOT):
                            continue
                    self.assertTrue(path.is_file(), f'{document}: {target}')


    def test_translations_preserve_examples_and_assets(self):
        source = (ROOT / "README.md").read_text()
        examples = re.findall(r"```(?:bash|powershell)\n(.*?)```", source, re.S)

        def assets(document):
            paths = re.findall(r'!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src="([^"]+)"', document.read_text())
            return sorted(
                target if target.startswith("https://") else str((document.parent / target).resolve())
                for pair in paths for target in pair if target
            )

        expected_assets = assets(ROOT / "README.md")
        for locale in ("zh-CN", "ja", "pt-BR", "es", "de"):
            document = ROOT / "docs" / "i18n" / f"README.{locale}.md"
            with self.subTest(locale=locale):
                self.assertEqual(
                    re.findall(r"```(?:bash|powershell)\n(.*?)```", document.read_text(), re.S),
                    examples,
                )
                self.assertEqual(assets(document), expected_assets)

    def test_localized_readmes_have_release_parity(self):
        """Translations keep the release-critical facts, links, and structure."""
        required_fragments = (
            "https://docs.astral.sh/uv/getting-started/installation/",
            "Everything",
            "Customize",
            "Firefox for Android",
            "Firefox + Chromium desktop",
            "Tailscale Serve",
            "sleeper mobile setup",
            "sleeper-firefox.xpi",
            "MCP",
            "CLI",
            "MIT",
            "o200k_base",
            "76.7%",
            "86.1%",
            "98.6%",
            "Helium 0.17.0.1",
            "Chromium 153.0.8010.36",
        )
        required_paths = {
            "docs/android.md",
            "docs/commands.md",
            "docs/agent-skill.md",
            "docs/installation.md",
            "CHANGELOG.md",
            "THIRD_PARTY_NOTICES.md",
            "PRIVACY.md",
            "SECURITY.md",
            "LICENSE",
            "docs/SPONSORS.md",
            "docs/benchmarks/matched-browser-interface.md",
        }
        root_h2_count = len(re.findall(r"^## ", (ROOT / "README.md").read_text(), re.M))

        for locale in ("zh-CN", "ja", "pt-BR", "es", "de"):
            document = ROOT / "docs" / "i18n" / f"README.{locale}.md"
            content = document.read_text()
            with self.subTest(locale=locale):
                for fragment in required_fragments:
                    self.assertIn(fragment, content, fragment)
                linked_paths = {
                    str((document.parent / target.split("#", 1)[0]).resolve().relative_to(ROOT.resolve()))
                    for target in re.findall(r"\]\(([^)]+)\)", content)
                    if "://" not in target and not target.startswith("#")
                }
                self.assertTrue(required_paths <= linked_paths, required_paths - linked_paths)
                self.assertGreaterEqual(len(re.findall(r"^## ", content, re.M)), root_h2_count)


if __name__ == '__main__':
    unittest.main()
