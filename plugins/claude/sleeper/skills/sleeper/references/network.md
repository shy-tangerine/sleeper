# Network and authenticated API operations

Inspect captured requests with the available `sleeper_network` tool or `sleeper network`. Choose the target tab explicitly and start with request metadata; request/response bodies can contain private data.

For an API call, use the declared `sleeper_api` schema or `sleeper api URL`. The URL must use HTTPS with no explicit port, and its exact host must be in the daemon's `SLEEPER_API_HOSTS` policy. The policy accepts hostnames rather than wildcards or URLs. Inspect the daemon's configured policy when troubleshooting rather than assuming a host is allowed; the project's command guide documents the defaults.

Sleeper captures authorization from the browser session and binds it to the host where it was observed. If no credential was captured for the requested host, let the user perform the site's normal sign-in/request flow and retry only after that host has a captured credential. An allowed host does not inherit another host's token.

Check the returned HTTP status, `ok` and intended application result. A policy rejection is resolved by reviewing the intended host and configuration, not by switching to HTTP, adding a port or extracting browser credentials. Keep results within the user's requested data scope.
