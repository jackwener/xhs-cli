# xhs-cli

[中文](README.md) | **English**

[![PyPI](https://img.shields.io/pypi/v/xhs-cli)](https://pypi.org/project/xhs-cli/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A command-line tool for [Xiaohongshu (小红书)](https://www.xiaohongshu.com) — search notes, view profiles, like, favorite, and comment, all from your terminal.

## Recommended Projects

- [twitter-cli](https://github.com/jackwener/twitter-cli) - A CLI tool for X/Twitter workflows
- [bilibili-cli](https://github.com/jackwener/bilibili-cli) - A CLI tool for Bilibili workflows

## Features

- **Search** — search notes by keyword with rich table output
- **Read** — view note content, stats, and comments
- **User Profile** — view user info, posts, followers, following
- **Feed** — get recommended content from explore page
- **Topics** — search for topics and hashtags
- **Engage** — like/unlike, favorite/unfavorite, comment, delete
- **Post** — publish image notes
- **Auth** — auto-extract cookies from Chrome, or browser-assisted QR login (terminal-rendered)
- **JSON output** — `--json` flag for all data commands
- **Auto token** — `xsec_token` is cached and auto-resolved

## Commands

| Category | Commands | Description |
|----------|----------|-------------|
| Auth | `login`, `logout`, `status`, `whoami` | Login, logout, check status, view profile |
| Read | `search`, `read`, `feed`, `topics` | Search notes, read details, explore feed, find topics |
| Users | `user`, `user-posts`, `followers`, `following` | View profile, list posts/followers/following |
| Engage | `like`, `unlike`, `comment`, `delete` | Like, unlike, comment, delete notes |
| Favorites | `favorite`, `unfavorite`, `favorites` | Favorite, unfavorite, list all favorites |
| Post | `post` | Publish a new image note |

> All data commands support `--json` for raw JSON output. `xsec_token` is auto-cached and auto-resolved.

## Installation

Requires Python 3.8+.

```bash
# Recommended: using uv
uv tool install xhs-cli

# Or using pipx
pipx install xhs-cli
```

<details>
<summary>Install from source (for development)</summary>

```bash
git clone git@github.com:jackwener/xhs-cli.git
cd xhs-cli
uv sync
```

</details>

## One-Command Local Smoke Test

With a valid saved session (`~/.xhs-cli/cookies.json`), run:

```bash
./scripts/smoke_local.sh
```

You can pass extra pytest arguments, for example:

```bash
./scripts/smoke_local.sh -k whoami
```

By default, only non-mutating smoke is executed
(`integration and not live_mutation`). To also verify
`like/favorite/comment/post/delete`, opt in explicitly:

```bash
XHS_SMOKE_MUTATION=1 ./scripts/smoke_local.sh
```

Optional environment variables:

```bash
XHS_SMOKE_COMMENT_TEXT="smoke test comment"
XHS_SMOKE_POST_IMAGES="/abs/a.jpg,/abs/b.jpg"
XHS_SMOKE_POST_TITLE="smoke title"
XHS_SMOKE_POST_CONTENT="smoke content"
```

## Usage

### Login

```bash
# Auto-extract cookies from Chrome (recommended)
xhs login

# Force QR code login (useful for troubleshooting auth)
xhs login --qrcode

# Or provide cookie string manually (must include a1 and web_session)
xhs login --cookie "a1=xxx; web_session=yyy"

# Quick check for saved login session
# (no browser needed, no browser-cookie extraction)
xhs status

# Show profile info
xhs whoami
xhs whoami --json

# Logout
xhs logout
```

### Search

```bash
xhs search "咖啡"
xhs search "咖啡" --json
```

### Read Note

```bash
# View note (xsec_token auto-resolved from cache)
xhs read <note_id>

# Include comments
xhs read <note_id> --comments

# Provide xsec_token manually if needed
xhs read <note_id> --xsec-token <token>
```

### User

```bash
# View user profile (uses internal user_id, not Red ID)
xhs user <user_id>

# List user's published notes
xhs user-posts <user_id>

# Followers / following
xhs followers <user_id>
xhs following <user_id>
```

### Feed & Topics

```bash
xhs feed
xhs topics "travel"
```

### Interactions

```bash
# Like / Unlike (xsec_token auto-resolved)
xhs like <note_id>
xhs like <note_id> --undo

# Favorite / Unfavorite
xhs favorite <note_id>
xhs favorite <note_id> --undo

# Comment
xhs comment <note_id> "nice post!"

# Delete your own note
xhs delete <note_id>

# List your favorites
xhs favorites
xhs favorites --max 10
```

### Post

```bash
xhs post "Title" --image photo1.jpg --image photo2.jpg --content "Body text"
xhs post "Title" --image photo1.jpg --content "Body text" --json

# Publish through a real Chrome session (when creator login cannot be reused via injected cookies)
xhs post-real "Title" --image photo1.jpg --content "Body text"
xhs post-real "Title" --image photo1.jpg --content "Body text" --cdp-url http://127.0.0.1:9222
```

### Other

```bash
xhs --version
xhs -v search "咖啡"   # debug logging
xhs --help
```

## Architecture

```
CLI (click) → XhsClient (camoufox browser)
                  ↓ navigate to real pages
              window.__INITIAL_STATE__ → extract structured data
```

Uses [camoufox](https://github.com/daijro/camoufox) (anti-fingerprint Firefox) to browse Xiaohongshu like a real user. Data is extracted from `window.__INITIAL_STATE__` — completely indistinguishable from normal browsing.

## How It Works

1. **Authentication** — First reads `~/.xhs-cli/cookies.json`; if missing, extracts cookies from local Chrome via browser-cookie3. `xhs login --qrcode` uses browser-assisted QR login with terminal half-block rendering (`▀ ▄ █`).
2. **Session Validation** — After login, the CLI verifies that the session is non-guest and probes feed/search usability. If probe fails, it asks for re-login.
3. **Browsing** — Each operation navigates to real pages using camoufox, making all traffic look like normal user browsing.
4. **Data Extraction** — Structured data is pulled from `window.__INITIAL_STATE__`.
5. **Token Caching** — After search/feed, `xsec_token` is auto-cached to `~/.xhs-cli/token_cache.json`.
6. **Interactions** — Like, favorite, and comment work by clicking actual DOM buttons.

## Use as AI Agent Skill

xhs-cli ships with a [`SKILL.md`](./SKILL.md) that teaches AI agents how to use it.

### Claude Code / Antigravity

```bash
# Clone into your project's skills directory
mkdir -p .agents/skills
git clone git@github.com:jackwener/xhs-cli.git .agents/skills/xhs-cli

# Or just copy the SKILL.md
curl -o .agents/skills/xhs-cli/SKILL.md \
  https://raw.githubusercontent.com/jackwener/xhs-cli/main/SKILL.md
```

Once added, AI agents that support the `.agents/skills/` convention will automatically discover and use xhs-cli commands.

### OpenClaw / ClawHub

Officially supports [OpenClaw](https://openclaw.ai) and [ClawHub](https://docs.openclaw.ai/tools/clawhub). Install via ClawHub:

```bash
clawhub install xiaohongshu-cli
```

All xhs-cli commands are available in OpenClaw after installation.

## Notes

- Cookies are stored in `~/.xhs-cli/cookies.json` with `0600` permissions.
- `xhs status` checks saved local cookies only and never triggers browser extraction.
- `xhs login --cookie` requires at least `a1` and `web_session`.
- Login runs a usability probe; guest/risk-limited sessions are treated as invalid and require re-login.
- `xhs post` may require an extra creator-platform login at `https://creator.xiaohongshu.com`.
- If `xhs post` says creator login is required but your real Chrome is already logged in, try `xhs post-real`.
- `xhs post-real` requires real Chrome to be started with remote debugging enabled, for example:
  `/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --profile-directory=Default`
- Uses headless Firefox via camoufox — no browser window is shown.
- First run requires downloading the camoufox browser (`python -m camoufox fetch`).
- User profile lookup requires the internal user_id (hex format), not the Red ID.

## License

Apache License 2.0
