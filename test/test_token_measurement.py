import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))
from token_measurement import sample


def test_sample_canonicalizes_dynamic_benchmark_values():
    measured = sample('http://127.0.0.1:41007 matched-1 matched-opencli-1-123456789 {"id":32}', '')
    assert measured['request_text'] == 'http://127.0.0.1:00000 matched-N matched-opencli-N-0000000000000 {"id":0}'


def test_published_samples_reencode_to_recorded_counts():
    data = json.loads((Path(__file__).resolve().parents[1] / "benchmarks/results/matched-token-samples.json").read_text())
    for interface in ("sleeper_cli", "sleeper_mcp", "opencli_cli", "playwright_mcp"):
        for run in data[interface]["runs"]:
            for step in run["steps"]:
                raw = step["raw"]
                assert len(__import__("tiktoken").get_encoding("o200k_base").encode(raw["request_text"])) == raw["request_tokens"]
                assert len(__import__("tiktoken").get_encoding("o200k_base").encode(raw["response_text"])) == raw["response_tokens"]


def test_all_published_protocol_samples_have_consistent_counts():
    import runpy
    import tiktoken

    root = Path(__file__).resolve().parents[1]
    policy = runpy.run_path(str(root / "scripts/check_public_tree.py"))
    encoding = tiktoken.get_encoding("o200k_base")

    def dictionaries(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from dictionaries(child)
        elif isinstance(value, list):
            for child in value:
                yield from dictionaries(child)

    checked = 0
    for name in sorted(policy["PUBLIC_ALLOWLIST"]):
        if not (name.startswith("benchmarks/results/") and name.endswith(".json")):
            continue
        data = json.loads((root / name).read_text())
        for item in dictionaries(data):
            if "runs" in item:
                assert item.get("status", "pass") == "pass", name
                assert item["runs"] and all(run.get("status") == "pass" for run in item["runs"]), name
            required = {"request_text", "response_text", "request_tokens", "response_tokens", "total_tokens"}
            if not required.issubset(item):
                continue
            request = len(encoding.encode(item["request_text"]))
            response = len(encoding.encode(item["response_text"]))
            assert (item["request_tokens"], item["response_tokens"], item["total_tokens"]) == (request, response, request + response), name
            checked += 1
    assert checked > 0


def test_readme_includes_measured_latency_and_memory():
    from statistics import median

    root = Path(__file__).resolve().parents[1]
    lines = (root / "README.md").read_text().splitlines()
    sources = {
        "Sleeper MCP": ("sleeper-mcp-matched-results.json", None),
        "Playwright MCP": ("playwright-mcp-token-results.json", None),
        "Sleeper CLI": ("matched-browser-interface-samples.json", "sleeper"),
        "OpenCLI": ("matched-browser-interface-samples.json", "opencli"),
    }
    for interface, (filename, key) in sources.items():
        data = json.loads((root / "benchmarks/results" / filename).read_text())
        if key is not None:
            data = data[key]
        assert data["status"] == "pass"
        assert len(data["runs"]) == 5
        elapsed = median(run["sequence_ms"] for run in data["runs"])
        memory = median(run["browser_process_scope"]["rss_bytes"] for run in data["runs"]) / 2**20
        row = next(line for line in lines if line.startswith(f"| {interface} |"))
        assert f"{elapsed:,.0f} ms" in row
        assert f"{memory:,.0f} MiB" in row


def test_readme_has_no_unmeasured_benchmark_cells():
    root = Path(__file__).resolve().parents[1]
    lines = (root / "README.md").read_text().splitlines()
    for interface in ("Sleeper CLI", "Sleeper MCP", "OpenCLI", "Playwright MCP", "Direct CDP"):
        row = next(line for line in lines if line.startswith(f"| {interface} |"))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 5
        assert cells[1].endswith(" ms")
        assert cells[2].endswith(" MiB")
        if interface == "Direct CDP":
            assert cells[3] == "Not applicable"
        else:
            assert cells[3].replace(",", "").isdigit()
        assert cells[4].split()[0].replace(",", "").isdigit()
