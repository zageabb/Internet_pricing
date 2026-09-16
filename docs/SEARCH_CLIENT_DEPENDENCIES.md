# Search client dependency compatibility

The web-search pipeline uses `ddgs` for the configured free search backends and `primp` as the HTTP client used internally by `ddgs`.

## Pinned versions

The application intentionally pins:

- `ddgs==9.16.0`
- `primp==2.0.1`

Keep these versions aligned when upgrading search dependencies.

## Why the pin exists

The previous `ddgs==9.5.5` release selected browser impersonation profiles from a hard-coded list containing older names such as `chrome_107`, `chrome_123`, `safari_17.2.1`, and `safari_17.5`.

Newer `primp` releases no longer accept those old profile names, which caused every configured search backend to fail before any request reached the search engine. Typical errors looked like:

```text
duckduckgo: Invalid impersonate: "chrome_107"
mojeek: Invalid impersonate: "safari_17.5"
startpage: Invalid impersonate: "safari_17.2.1"
yahoo: Invalid impersonate: "chrome_123"
```

`ddgs==9.16.0` delegates profile selection to `primp` using `impersonate="random"` and `impersonate_os="random"`, avoiding the obsolete hard-coded profile list.

## Upgrade rule

When changing either `ddgs` or `primp`:

1. Upgrade them together in a test environment.
2. Run the full pytest suite.
3. Confirm the configured text backends still exist: DuckDuckGo, Mojeek, Startpage, and Yahoo.
4. Run at least one live search after deployment.
5. Treat `Invalid impersonate` as a search-client dependency problem first, not as four independent search-engine failures.

The regression tests in `tests/test_search_client_compat.py` verify the pinned versions, the random impersonation behaviour, and continued availability of the configured backends.
