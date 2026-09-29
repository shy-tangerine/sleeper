# OpenCLI browser parity

Sleeper exposes the browser-control primitives below through its CLI and browser extension. The MCP bridge exposes a subset; see the [schema inventory](mcp-tools.json).

## Covered

- Navigation: `goto`, `back`, tabs, and frames.
- DOM inspection: `state`, `snapshot`, `find`, `get`, `read`, `read_all`, `extract`, and `forms`.
- Interaction: `click`, `click_all`, `click_text`, `type`, `keys`, `press`, `hover`, `focus`, `dblclick`, `check`, `uncheck`, `drag`, and `select`.
- Observation: `wait`, structured `wait_until`, `wait_text`, `wait_url`, `wait_xhr`, `wait_dialog`, `network`, `media`, and `console`.
- Browser operations: `api`, `dialog`, `shot`/`screenshot`, and `newtab`.
- Vocabulary aliases: `eval` → `exec`, `fill` → `fill_form`, `tab list`, and `tab new`. Arbitrary `exec` and JavaScript-string `wait_until` predicates are Chromium-only; signed Firefox builds use structured wait conditions.
- Semantic locators: `--role`, `--name`, `--label`, `--text`, and `--testid` for `find` and core write actions.
- Stable refs from `find` and snapshot headings/form controls, accepted as `@sleeper-N`.
- Tab selection and closing through `tab select` and `tab close`.
- Chromium MV3 service-worker startup and daemon WebSocket connection in a fresh real Chromium profile.
- Chromium full-page and annotated screenshots with viewport overrides.
- Firefox viewport, full-page, and annotated screenshots through its public capture API.
- Download waits through `wait download <pattern>`.
- URL site analysis through `analyze`.
- Adapter scaffolding and verification through `adapter init|verify`.
- Stable installation-ID routing through `SLEEPER_PROFILE=<id>`.
- Session lifecycle aliases: `bind <name>`, `unbind`, and `close`.

## Remaining work

- Broader real-browser regression coverage beyond the safe smoke suite.

File uploads use explicit base64 content through MCP; native-path and filename-only CLI uploads are unsupported. See the [file upload contract](commands.md#file-uploads).
