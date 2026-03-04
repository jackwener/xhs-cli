# xhs-cli 🍰

[English](README.md) | **中文**

小红书命令行工具 — 在终端中搜索笔记、查看主页、点赞、收藏、评论。

## ✨ 功能

- 🔍 **搜索** — 按关键词搜索笔记，Rich 表格展示
- 📖 **阅读** — 查看笔记内容、数据、评论
- 👤 **用户资料** — 查看用户信息
- 📝 **用户笔记** — 列出用户发布的所有笔记
- 🏠 **推荐 Feed** — 获取探索页推荐内容
- 🏷️ **话题** — 搜索话题标签
- ❤️ **点赞 / 取消** — 给笔记点赞或取消
- ⭐ **收藏 / 取消** — 收藏或取消收藏笔记
- 💬 **评论** — 发表评论
- 🔐 **认证** — 自动提取 Chrome cookie，或扫码登录
- 📊 **JSON 输出** — 所有数据命令支持 `--json`
- 🔗 **Token 自动缓存** — 搜索/Feed 结果的 `xsec_token` 自动缓存，后续命令免手动传

## 📋 命令一览

| 分类 | 命令 | 说明 |
|------|------|------|
| 🔐 **认证** | `login`, `logout`, `status`, `whoami` | 登录、退出、状态检查、查看个人资料 |
| 🔍 **浏览** | `search`, `read`, `feed`, `topics` | 搜索笔记、阅读详情、推荐 Feed、搜索话题 |
| 👤 **用户** | `user`, `user-posts`, `followers`, `following` | 查看资料、列出笔记/粉丝/关注 |
| ❤️ **互动** | `like`, `unlike`, `comment` | 点赞、取消点赞、评论 |
| ⭐ **收藏** | `favorite`, `unfavorite`, `favorites` | 收藏、取消收藏、查看收藏列表 |
| 📝 **发布** | `post` | 发布图文笔记 |

> 所有数据命令支持 `--json` 输出原始 JSON。`xsec_token` 自动缓存，无需手动传递。

## 🏗️ 架构

```
CLI (click) → XhsClient (camoufox 浏览器)
                  ↓ 导航到真实页面
              window.__INITIAL_STATE__ → 提取结构化数据
```

使用 [camoufox](https://github.com/nicochichat/camoufox)（反指纹 Firefox）像真实用户一样浏览小红书。数据从页面的 `window.__INITIAL_STATE__` 中提取，与正常浏览完全一致。

## 📦 安装

需要 Python 3.8+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
# 克隆并安装
git clone git@github.com:jackwener/xhs-cli.git
cd xhs-cli
uv sync

# 安装 camoufox 浏览器
uv run python -m camoufox fetch
```

也可以从 PyPI 安装：

```bash
pip install xhs-cli
```

## 🚀 使用

### 登录

```bash
# 自动从 Chrome 提取 cookie（推荐）
uv run xhs login

# 手动提供 cookie 字符串
uv run xhs login --cookie "a1=xxx; web_session=yyy"

# 快速检查登录状态（不启动浏览器）
uv run xhs status

# 查看完整个人资料
uv run xhs whoami
uv run xhs whoami --json

# 退出登录
uv run xhs logout
```

### 搜索

```bash
# 搜索，Rich 表格展示
uv run xhs search "咖啡"

# JSON 输出
uv run xhs search "咖啡" --json
```

### 阅读笔记

```bash
# 查看笔记（xsec_token 从缓存自动解析）
uv run xhs read <note_id>

# 包含评论
uv run xhs read <note_id> --comments

# 手动指定 xsec_token
uv run xhs read <note_id> --xsec-token <token>

# JSON 输出
uv run xhs read <note_id> --json
```

### 用户资料 & 笔记

```bash
# 查看用户资料（使用内部 user_id，非小红书号）
uv run xhs user <user_id>
uv run xhs user <user_id> --json

# 列出用户发布的笔记
uv run xhs user-posts <user_id>
uv run xhs user-posts <user_id> --json
```

### 推荐 & 话题

```bash
# 获取推荐页内容
uv run xhs feed
uv run xhs feed --json

# 搜索话题
uv run xhs topics "咖啡"
uv run xhs topics "咖啡" --json
```

### 互动

```bash
# 点赞 / 取消点赞（xsec_token 自动解析）
uv run xhs like <note_id>
uv run xhs like <note_id> --undo

# 收藏 / 取消收藏
uv run xhs favorite <note_id>
uv run xhs favorite <note_id> --undo

# 评论
uv run xhs comment <note_id> "好棒！"
```

### 其他选项

```bash
# 查看版本
uv run xhs --version

# 开启调试日志
uv run xhs -v search "咖啡"

# 查看帮助
uv run xhs --help
uv run xhs search --help
```

## 📁 项目结构

```
xhs-cli/
├── pyproject.toml         # 项目配置和依赖
├── uv.lock                # 锁文件
├── README.md              # 英文文档
├── README_CN.md           # 中文文档
├── LICENSE
└── xhs_cli/
    ├── __init__.py         # 包版本
    ├── cli.py              # Click CLI 命令
    ├── client.py           # Camoufox 浏览器客户端
    ├── auth.py             # Cookie 提取 + 扫码登录 + Token 缓存
    └── exceptions.py       # 自定义异常
```

## 🔧 工作原理

1. **认证**：通过 [browser-cookie3](https://github.com/nicochichat/browsercookie) 从本地 Chrome 提取 cookie。提取失败则 fallback 到扫码登录。

2. **浏览**：每个操作都使用 camoufox（反指纹 Firefox）导航到真实页面，所有流量与正常用户浏览一致。

3. **数据提取**：从 `window.__INITIAL_STATE__` 中提取结构化数据，这是 Vue/React 渲染页面时使用的同一份数据。

4. **Token 缓存**：搜索/Feed/用户笔记执行后，`xsec_token` 自动缓存到 `~/.xhs-cli/token_cache.json`，后续命令自动解析，无需手动复制粘贴。

5. **互动操作**：点赞、收藏、评论通过找到并点击真实 DOM 按钮实现 — 与真实用户操作完全一致。

## ⚠️ 注意事项

- Cookie 存储在 `~/.xhs-cli/cookies.json`，权限 `0600`（仅 owner 可读写）。
- Token 缓存存储在 `~/.xhs-cli/token_cache.json`。
- 使用 headless Firefox（camoufox），不会弹出浏览器窗口。
- 首次运行可能较慢，因为 camoufox 需要下载浏览器。
- 用户资料查询需要内部 user_id（十六进制格式），不是小红书号（数字格式）。

## 📄 许可证

Apache License 2.0
