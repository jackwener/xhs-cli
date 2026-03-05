# xhs-cli

[中文](README.md) | **English**

[![PyPI](https://img.shields.io/pypi/v/xhs-cli)](https://pypi.org/project/xhs-cli/)
[![License](https://img.shields.io/github/license/jackwener/xhs-cli)](LICENSE)

A command-line tool for [Xiaohongshu (小红书)](https://www.xiaohongshu.com) — search notes, view profiles, like, favorite, and comment, all from your terminal.

## Features

- **Search** — search notes by keyword with rich table output
- **Read** — view note content, stats, and comments
- **User Profile** — view user info, posts, followers, following
- **Feed** — get recommended content from explore page
- **Topics** — search for topics and hashtags
- **Engage** — like/unlike, favorite/unfavorite, comment
- **Post** — publish image notes
- **Auth** — auto-extract cookies from Chrome, or login via QR code
- **JSON output** — `--json` flag for all data commands
- **Auto token** — `xsec_token` is cached and auto-resolved

## Commands

| Category | Commands | Description |
|----------|----------|-------------|
| Auth | `login`, `logout`, `status`, `whoami` | Login, logout, check status, view profile |
| Read | `search`, `read`, `feed`, `topics` | Search notes, read details, explore feed, find topics |
| Users | `user`, `user-posts`, `followers`, `following` | View profile, list posts/followers/following |
| Engage | `like`, `unlike`, `comment` | Like, unlike, comment on notes |
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

## Usage

### Login

```bash
# Auto-extract cookies from Chrome (recommended)
xhs login

# Or provide cookie string manually
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

# List your favorites
xhs favorites
xhs favorites --max 10
```

### Post

```bash
xhs post "Title" --image photo1.jpg --image photo2.jpg --content "Body text"
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

1. **Authentication** — First reads `~/.xhs-cli/cookies.json`; if missing, extracts cookies from local Chrome via browser-cookie3. Falls back to QR code login if extraction fails.
2. **Browsing** — Each operation navigates to real pages using camoufox, making all traffic look like normal user browsing.
3. **Data Extraction** — Structured data is pulled from `window.__INITIAL_STATE__`.
4. **Token Caching** — After search/feed, `xsec_token` is auto-cached to `~/.xhs-cli/token_cache.json`.
5. **Interactions** — Like, favorite, and comment work by clicking actual DOM buttons.

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
- Uses headless Firefox via camoufox — no browser window is shown.
- First run requires downloading the camoufox browser (`python -m camoufox fetch`).
- User profile lookup requires the internal user_id (hex format), not the Red ID.

## License

Apache License 2.0
