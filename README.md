# xhs-cli

**中文** | [English](README_EN.md)

[![PyPI](https://img.shields.io/pypi/v/xhs-cli)](https://pypi.org/project/xhs-cli/)
[![License](https://img.shields.io/github/license/jackwener/xhs-cli)](LICENSE)

小红书命令行工具 — 在终端中搜索笔记、查看主页、点赞、收藏、评论。

## 功能

- **搜索** — 按关键词搜索笔记，Rich 表格展示
- **阅读** — 查看笔记内容、数据、评论
- **用户资料** — 查看用户信息、笔记、粉丝、关注
- **推荐 Feed** — 获取探索页推荐内容
- **话题** — 搜索话题标签
- **互动** — 点赞/取消、收藏/取消、评论
- **发布** — 发布图文笔记
- **认证** — 自动提取 Chrome cookie，或扫码登录
- **JSON 输出** — 所有数据命令支持 `--json`
- **Token 自动缓存** — `xsec_token` 搜索后自动缓存，后续命令免手动传

## 命令一览

| 分类 | 命令 | 说明 |
|------|------|------|
| Auth | `login`, `logout`, `status`, `whoami` | 登录、退出、状态检查、查看个人资料 |
| Read | `search`, `read`, `feed`, `topics` | 搜索笔记、阅读详情、推荐 Feed、搜索话题 |
| Users | `user`, `user-posts`, `followers`, `following` | 查看资料、列出笔记/粉丝/关注 |
| Engage | `like`, `unlike`, `comment` | 点赞、取消点赞、评论 |
| Favorites | `favorite`, `unfavorite`, `favorites` | 收藏、取消收藏、查看收藏列表 |
| Post | `post` | 发布图文笔记 |

> 所有数据命令支持 `--json` 输出。`xsec_token` 自动缓存，无需手动传递。

## 安装

需要 Python 3.8+。

```bash
# 推荐：使用 uv
uv tool install xhs-cli

# 或使用 pipx
pipx install xhs-cli
```

<details>
<summary>从源码安装（开发用）</summary>

```bash
git clone git@github.com:jackwener/xhs-cli.git
cd xhs-cli
uv sync
```

</details>

## 使用

### 登录

```bash
# 自动从 Chrome 提取 cookie（推荐）
xhs login

# 手动提供 cookie 字符串
xhs login --cookie "a1=xxx; web_session=yyy"

# 快速检查已保存的登录状态（不启动浏览器，不读取浏览器 cookie）
xhs status

# 查看个人资料
xhs whoami
xhs whoami --json

# 退出登录
xhs logout
```

### 搜索

```bash
xhs search "咖啡"
xhs search "咖啡" --json
```

### 阅读笔记

```bash
# 查看笔记（xsec_token 从缓存自动解析）
xhs read <note_id>

# 包含评论
xhs read <note_id> --comments

# 手动指定 xsec_token
xhs read <note_id> --xsec-token <token>
```

### 用户

```bash
# 查看用户资料（使用内部 user_id，非小红书号）
xhs user <user_id>

# 列出用户笔记
xhs user-posts <user_id>

# 粉丝 / 关注
xhs followers <user_id>
xhs following <user_id>
```

### 推荐 & 话题

```bash
xhs feed
xhs topics "旅行"
```

### 互动

```bash
# 点赞 / 取消（xsec_token 自动解析）
xhs like <note_id>
xhs like <note_id> --undo

# 收藏 / 取消
xhs favorite <note_id>
xhs favorite <note_id> --undo

# 评论
xhs comment <note_id> "好棒！"

# 查看收藏列表
xhs favorites
xhs favorites --max 10
```

### 发布笔记

```bash
xhs post "标题" --image photo1.jpg --image photo2.jpg --content "正文内容"
```

### 其他

```bash
xhs --version
xhs -v search "咖啡"   # 调试日志
xhs --help
```

## 架构

```
CLI (click) → XhsClient (camoufox 浏览器)
                  ↓ 导航到真实页面
              window.__INITIAL_STATE__ → 提取结构化数据
```

使用 [camoufox](https://github.com/daijro/camoufox)（反指纹 Firefox）像真实用户一样浏览小红书。数据从页面的 `window.__INITIAL_STATE__` 中提取，与正常浏览完全一致。

## 工作原理

1. **认证** — 优先读取 `~/.xhs-cli/cookies.json`；未命中时通过 browser-cookie3 从本地 Chrome 提取 cookie，失败则 fallback 到扫码登录。
2. **浏览** — 使用 camoufox 导航到真实页面，所有流量与正常用户浏览一致。
3. **数据提取** — 从 `window.__INITIAL_STATE__` 提取结构化数据。
4. **Token 缓存** — 搜索/Feed 后 `xsec_token` 自动缓存到 `~/.xhs-cli/token_cache.json`。
5. **互动操作** — 点赞、收藏、评论通过点击真实 DOM 按钮实现。

## 作为 AI Agent Skill 使用

xhs-cli 自带 [`SKILL.md`](./SKILL.md)，让 AI Agent 能自动学习并使用本工具。

### Claude Code / Antigravity

```bash
# 克隆到项目的 skills 目录
mkdir -p .agents/skills
git clone git@github.com:jackwener/xhs-cli.git .agents/skills/xhs-cli

# 或者只复制 SKILL.md
curl -o .agents/skills/xhs-cli/SKILL.md \
  https://raw.githubusercontent.com/jackwener/xhs-cli/main/SKILL.md
```

添加后，支持 `.agents/skills/` 的 AI Agent 会自动发现并使用 xhs-cli 命令。

### OpenClaw / ClawHub

官方支持 [OpenClaw](https://openclaw.ai) 和 [ClawHub](https://docs.openclaw.ai/tools/clawhub) 生态。通过 ClawHub 安装：

```bash
clawhub install xiaohongshu-cli
```

安装后即可在 OpenClaw 中直接使用所有 xhs-cli 命令。

## 注意事项

- Cookie 存储在 `~/.xhs-cli/cookies.json`，权限 `0600`。
- `xhs status` 只检查本地已保存 cookie，不会触发浏览器 cookie 提取。
- 使用 headless Firefox，不会弹出浏览器窗口。
- 首次运行需下载 camoufox 浏览器（`python -m camoufox fetch`）。
- 用户资料查询需要内部 user_id（十六进制），不是小红书号。

## License

Apache License 2.0
