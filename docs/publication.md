# Public release boundary

The current Sleeper checkout is a private staging repository. Its Git history
contains maintainer-only material and must never be made public. A public
release starts from a fresh, history-free directory created from the reviewed
working tree.

## Build a candidate without history

From the staging checkout, run:

```bash
uv run python scripts/export-public.py ../sleeper-public-candidate
```

The exporter fails closed when it finds an unreviewed path, a symlink, a
missing Git checkout, or a destination inside the source checkout. It includes
tracked files plus non-ignored working-tree files that pass
`scripts/check_public_tree.py`; it never reads or copies `.git`, ignored local
state, build output, research, or wiki directories. The destination must be
new, so an old candidate cannot be silently overwritten.

Validate the candidate independently:

```bash
cd ../sleeper-public-candidate
uv run python scripts/check_public_tree.py
uv run pytest -q test
bash test/run.sh
./scripts/build-xpi.sh
./scripts/build-chromium.sh
```

The exporter and validation are preparation tools only. They do not create a
remote, change GitHub visibility, push a branch, create a tag or release, or
submit the Firefox add-on. Keep the staging checkout and the candidate private
until the maintainer has reviewed the exact candidate and separately approved
the concrete public destination.

## Publication gates

Before any visibility change, the maintainer must independently confirm:

1. the candidate contains no private paths, credentials, account data, local
   URLs, or generated release state;
2. a clean clone can reproduce the submitted browser packages and install the
   daemon and CLI using only public files;
3. `PRIVACY.md`, `SECURITY.md`, the manifest permissions and data-collection
   declaration, and the AMO listing agree with the shipped behavior;
4. repository settings, issue/PR history, releases, tags, wiki, Actions logs,
   and artifacts are either clean or deliberately kept private; and
5. explicit approval is given for that exact destination and commit.

Only after those gates are met may a maintainer initialize a new Git history,
review the resulting diff, configure a remote, and publish. No command in this
document is authorization to perform those external actions.

## PyPI and MCP Registry boundary

The future Python distribution candidate is `sleeper-cli`; the generic PyPI
name `sleeper` is already occupied by an unrelated package. Its runtime
package would provide the Python CLI,
daemon, and stdio MCP launcher. It would not contain the browser extension or
its Firefox/Chromium packages, native agent plugins, skill files, installer,
or service definitions. Those remain separate release artifacts and are still
needed for a working browser connection; a source archive may also include
packaging metadata and offline tests.

The MCP Registry stores server metadata, not the package artifact. A future
submission would therefore require a published PyPI release first, then a
separately reviewed `server.json` with a registry namespace, `registryType`
`pypi`, the package identifier and version, and stdio transport metadata. The
official registry currently verifies PyPI ownership through an
`mcp-name: <server-name>` marker in the package README and requires namespace
authentication. Validate that metadata with the official `mcp-publisher` tool
and obtain the required namespace/authentication before any submission. No
`server.json`, registry login, or registry publication is created by this
repository's packaging work.

See the [official registry package-type requirements](https://modelcontextprotocol.io/registry/package-types)
and [official registry requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md)
for the current rules; the registry is in preview and those rules may change.
