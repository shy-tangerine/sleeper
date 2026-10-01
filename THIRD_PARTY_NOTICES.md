# Third-party notices

Sleeper's source and project-authored assets are released under the Apache
License 2.0 in `LICENSE`. This file records external dependencies and the
provenance of assets included in the source tree or browser packages.

## Runtime Python dependencies

These dependencies are declared in `pyproject.toml` and pinned in `uv.lock`.
They are installed separately; no Python dependency source is vendored in
Sleeper.

| Package | Version | License | Project |
| --- | --- | --- | --- |
| `detect-secrets` | 1.5.0 | Apache-2.0 | [Yelp/detect-secrets](https://github.com/Yelp/detect-secrets) |
| `qrcode` | 8.2 | BSD-3-Clause | [python-qrcode](https://github.com/lincolnloop/python-qrcode) |
| `websockets` | 16.0 | BSD-3-Clause | [python-websockets/websockets](https://github.com/python-websockets/websockets) |

The `detect-secrets` attribution is Copyright Yelp, Inc. and contributors;
upstream license and notice text apply to that dependency. The other listed
dependencies retain their upstream copyright and attribution notices in their
separately installed distributions.

The runtime closure resolved by `uv` also includes the following transitive
packages. They are not bundled in the extension or native plugin artifacts:

| Package | Version | License | Used by |
| --- | --- | --- | --- |
| `PyYAML` | 6.0.3 | MIT | `detect-secrets` |
| `requests` | 2.34.2 | Apache-2.0 | `detect-secrets` |
| `certifi` | 2026.7.22 | MPL-2.0 | `requests` |
| `charset-normalizer` | 3.5.1 | MIT | `requests` |
| `idna` | 3.19 | BSD-3-Clause | `requests` |
| `urllib3` | 2.7.0 | MIT | `requests` |

`uv tree --all-groups` also resolves `pytest`, `tiktoken`, `playwright`,
`psutil`, and their transitive dependencies in the `dev` and `benchmark`
groups. Those are development and measurement tools only; they are not
runtime or release-package contents.

## Release and asset provenance

The package builders copy project runtime files, the icon set, `LICENSE`, and
this notice. They do not bundle the browser distribution in `AppDir/`, Python
dependencies, fonts, or third-party JavaScript/CSS source.

| Asset set | Files | Evidence and status |
| --- | --- | --- |
| Toolbar state icons | `extension/icon.svg`, `extension/icon-active.svg`, `extension/icon*.png`, `extension/icon-active*.png` | Project-authored single-eye idle/active SVGs and raster size variants. The SVG/PNG set was introduced by commit `32721b4`; PNG inspection found no author, copyright, software, or external-source metadata. |
| Native plugin icons | `plugins/claude/sleeper/assets/icon.svg`, `plugins/codex/sleeper/assets/icon.svg` | Exact-byte copies of `extension/icon-active.svg`. The canonical skill lives in `plugins/codex/sleeper/skills/sleeper/` and is copied into the Claude plugin. Both adapters include generated client manifests and the local `sleeper-mcp` launcher declaration; they do not vendor a client SDK or runtime. |
| Repository presentation | `assets/repository-hero.png`, `assets/repository-social-preview.png` | Project-generated Sleeper artwork. Current SHA-256 values are `8a9de02b627a3dff5cd7d91a71ebd25e9539212f486cc8986a003955dcd3acc7` (hero, 1774×887) and `4a096e203ab4ca9edfe3ffd92a13c1508412faaf225fccf913e9ef5c2582ee89` (social preview, 1280×640). The hero's source and reproducible vectorization record are retained outside the release tree. |
| Benchmark captures | `benchmarks/results/*` | Public result fixtures contain protocol payloads and measurements, not vendored benchmark repositories. OpenCLI payloads were captured from [OpenCLI](https://github.com/jackwener/opencli) at revision `8271afc67e8504bda94c147f446ee29775d08274`; the captured payloads are Copyright 2025 jackwener and licensed Apache-2.0 with the upstream project. Private browser distributions, vendor checkouts, and run output are ignored and excluded from the public export. |

No external artwork source or third-party asset is claimed for the project
icons or repository artwork. The visual review found only the Sleeper mark,
abstract artwork, and synthetic benchmark content; it found no personal or
account material.

## Package inspection (2026-09-13)

The reproducibly rebuilt packages contain the following member counts:

| Package | Members | Required notices |
| --- | ---: | --- |
| `build/sleeper.xpi` | 35 | `LICENSE`, `THIRD_PARTY_NOTICES.md` |
| `build/sleeper-chromium.zip` | 36 | `LICENSE`, `THIRD_PARTY_NOTICES.md` |

Both packages contain the browser-specific manifest, Sleeper JavaScript,
HTML/CSS, the SVG and PNG toolbar icons, and the two required notices. No
browser binary, font, Python dependency, or copied third-party source tree is
present. Package contents are generated from the current checkout and are
ignored build output, not source-tree files.

The Chromium MV3 manifest requests `tabs`, `activeTab`, `storage`,
`webRequest`, `scripting`, `debugger`, and `downloads`, with broad HTTP(S)
host access. The Firefox MV2 manifest requests tabs, storage, request
interception, local relay access, and broad HTTP(S) host access. These
permissions are implementation requirements; they do not grant browser-vendor
support, account access, or a service-level promise.

## Metadata consistency

The root `LICENSE`, README license link/badge, `pyproject.toml`, native plugin
manifests, and skill front matter identify Apache-2.0. Browser manifests have
no license field; their accompanying source and package notices provide the
license information.
