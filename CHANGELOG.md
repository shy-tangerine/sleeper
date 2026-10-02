# Changelog

## Unreleased

### Fixed

- Tab inventories expose stable `id:` selectors for navigation, page actions, selection, and closing. Missing IDs and ambiguous URL selectors fail instead of targeting another tab.
- Numeric tab selectors now match the global `index` displayed by `tab list` across windows; the browser’s per-window position is exposed as `windowIndex`.
