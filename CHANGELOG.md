# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Fixed

- **Read commands no longer depend on `window.__INITIAL_STATE__`**, which
  Xiaohongshu's current web frontend no longer injects (it renders purely via
  client-side XHR). `search`, `feed`, `whoami`, and `read` were timing out;
  they now work again.

### Changed

- Added `XhsClient._navigate_and_capture()`, which navigates to a page and reads
  the body of the SPA's own validly-signed XHR response via
  `page.expect_response`, instead of forging API calls.
- Migrated `search_notes` (`/api/sns/web/v1/search/notes`), `get_feed`
  (`/api/sns/web/v1/homefeed`, scroll-triggered), `get_self_info`
  (`/api/sns/web/v2/user/me`), and `get_note_comments`
  (`/api/sns/web/v2/comment/page`) to this mechanism. `get_note_detail` scrapes
  the rendered DOM, since direct note opens fire no detail XHR.

### Known limitations

- Profile-page commands (`user`, `user-posts`, `followers`, `following`,
  `favorites`) still rely on `__INITIAL_STATE__`. Under headless automation all
  `/user/profile/<id>` pages redirect to a risk-control captcha, so they cannot
  be migrated with the same approach and remain non-functional for now.
- `read` note-detail fields are best-effort DOM scrapes; engagement counts may
  be approximate.

### Validation

- `pytest tests/test_client.py tests/test_cli.py tests/test_auth.py` → 82 passed.
- Live-verified against a logged-in account: `search`, `feed`, `whoami`, `read`.

## v0.1.4 - 2026-03-11

### Changed

- Reworked `xhs login --qrcode` to use a browser-assisted network-response flow.
- Removed the legacy DOM/screenshot-based QR extraction path.
- Synced README and README_EN to the current QR login behavior.

### Validation

- `python -m compileall xhs_cli` passes.
- `uv run pytest tests/test_auth.py tests/test_cli.py` passes (`61 passed`).

## v0.1.2 - 2026-03-06

### Added

- Added terminal QR rendering with half-block characters (`▀`, `▄`, `█`) for QR login.
- Added post-login session usability probing (feed/search) to detect limited/guest sessions.
- Added stricter and broader test coverage for auth, CLI login flows, and publish heuristics.
- Added `qrcode` dependency for terminal QR rendering.

### Changed

- Strengthened cookie requirements for saved/manual auth:
  - Required cookies are now `a1` + `web_session`.
- Improved QR login robustness:
  - Switched `xhs login --qrcode` to a browser-assisted network-response flow.
  - Export QR URL from `login/qrcode/create` instead of scraping page DOM.
  - Export session cookies after `login/qrcode/status` instead of guessing from page state.
- Improved login success detection:
  - Treat guest sessions as invalid.
  - Wait for post-login browser session stabilization before persisting cookies.
- Improved operation reliability:
  - Tightened success criteria for publish/comment/delete flows.
  - Added strict data-wait timeout path to reduce silent empty results.
- Updated `whoami --json` to include normalized top-level fields when resolvable.
- Updated docs (`README.md` and `README_EN.md`) to match current login/auth behavior.

### Fixed

- Fixed transient cookie verification flow to avoid unintended QR login fallback.
- Fixed favorites note ID extraction regex to support alphanumeric note IDs.
- Fixed cross-platform cookie save behavior by handling `chmod` failures safely.
- Fixed multiple false-positive success cases in interaction and publish flows.

### Validation

- `ruff check .` passes.
- `pytest -q` passes (`66 passed, 21 deselected`).
