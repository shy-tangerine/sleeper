# Browser fixtures

Run `npm ci --ignore-scripts` and serve the repository with `python3 -m http.server 8765 --bind 127.0.0.1`. Open <http://127.0.0.1:8765/test/fixtures/controlled-inputs.html> in a disposable browser profile.

The controlled-input fixture runs the current page handlers against pinned React 18 and Vue 3 packages from local `node_modules`. It checks both the DOM value and the framework model after a task tick, including clear, stealth typing, empty values, and an input that rejects changes. The page title reports `PASS` or `FAIL`; the results list names each check. No daemon or signed-in browser is needed. This verifies framework behavior but does not replace the live GitHub and Wikipedia checks in issue #6.
