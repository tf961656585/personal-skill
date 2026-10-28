---
name: context-whale
description: |
  仅当用户显式输入 /context-whale 时使用；不要在用户提到上下文窗口、token、优化、压缩等词时自动调用。
  把当前 harness 会话的上下文构成渲染成鲸鱼娘便当图，并输出可分析 JSON。
when_to_use: |
  只在用户显式输入 /context-whale，或明确说“运行 context-whale”时使用。不要自动触发。
version: 0.0.4
metadata: context-whale v0.0.4
---

# Context Whale · 上下文鲸鱼娘

**触发门禁：只在用户显式输入 `/context-whale` 时执行。** 用户只是聊到上下文、token、窗口、优化时，不要加载或运行本 skill。ZCode 的 skill frontmatter 没有 `disable-model-invocation` 开关，所以门禁由三件事共同保证：`/context-whale` command、本段描述、以及脚本的 `--explicit` 参数。

## 它做什么

读取当前 harness 的会话记录，把“这一轮模型实际看到的上下文”拆成 12 类，按真实 token 总量校准占比，然后渲染成一张鲸鱼娘便当图：

- `context-whale.html`：可直接在会话里打开的静态报告
- `context-report.json`：稳定 schema，供后续趋势分析
- `data/history.jsonl`：每次运行的紧凑历史

## 执行流程

1. 从本轮 system context 里找到本会话的**可写可视化目录**（形如 `~/.zcode/v2/visualizations/<hash>`），记为 `OUT`。找不到时用 `/tmp/context-whale-<session>`。
2. 如果需要刷新素材（用户传了 `--refresh-assets`），先运行：
   ```bash
   python3 ~/.agents/skills/context-whale/scripts/context_whale.py bootstrap-assets --explicit --run
   ```
3. 运行：
   ```bash
   python3 ~/.agents/skills/context-whale/scripts/context_whale.py run \
     --explicit --out "$OUT" $ARGUMENTS
   ```
4. 读取 stdout 的 JSON：
   - `ok: true`：把 `html_path` 作为 Markdown 链接给用户；用 2–3 句话说明 `summary.headline`、占比前三、以及 `summary.insights` 的第一条动作。
   - `error.code == "assets_missing"`：运行 `bootstrap-assets --explicit --run`，再重跑第 3 步。
   - `error.code == "session_not_found"`：先跑 `list`，把候选会话列给用户，请用户用 `--session` 指定。
5. 不要把完整 HTML 或 JSON 粘贴到聊天里；链接 + 结论即可。

## 常用参数

```bash
# 当前目录/当前会话
/context-whale

# 指定会话
/context-whale --session sess_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 指定 harness（跨 harness）
/context-whale --harness codex --session <thread_id>
/context-whale --harness claude_code --session <path.jsonl>
/context-whale --harness dsh --session <path.jsonl.zstd>
/context-whale --harness pi --session <path.jsonl>

# 只看 JSON，不渲染
/context-whale --json-only

# 重新生成鲸鱼娘素材（需要 IARTStudio 运行）
/context-whale --refresh-assets
```

## Harness 适配与保真度

| Harness | 数据源 | 保真度 | 备注 |
|---|---|---|---|
| ZCode | `~/.zcode/cli/db/db.sqlite` + `~/.zcode/cli/rollout/model-io-*.jsonl` | **L1 完整请求** | system、tools schema、messages、usage 全有；需过滤 `session_title` 记录，并做 full+tail 重建 |
| DeepSeek Harness | `~/.dsh/sessions/<encoded-cwd>/*/session.v3.jsonl.zstd` | **L1 完整请求** | `request/header.tools`、`system/message`、`request/context.contextWindow`、`usage` |
| Claude Code | `~/.claude/projects/<encoded-cwd>/*.jsonl` | **L2 会话级** | 有每条 assistant 的 usage 与 thinking/tool_use/tool_result；**没有** system prompt 和工具 schema |
| Codex / ChatGPT app | `~/.codex/thread_history_1.sqlite` + `state_5.sqlite` | **L2 会话级** | `thread_items` 有消息/工具输出；`tokens_used` 是线程累计值；内置工具 schema 不落盘 |
| Pi / OpenClaw | `~/.openclaw/agents/main/sessions/*.jsonl` 或 `~/.pi/sessions` | **L2 会话级** | 有 message usage；没有 system/tools |

**L2 的规则**：缺失的类别显示为「未记录」，不是 0；占比只覆盖已落盘的消息。`context-report.json` 里用 `coverage` 和 `fidelity` 标出来。

## 输出文件

```text
<OUT>/
├── context-whale.html       # 报告
├── context-report.json      # 稳定 schema
└── assets/                  # 便当头图、头像、透明图标
```

`report.json` 的关键字段：

- `harness` / `fidelity` / `coverage`
- `window.{limit, used, pct}`
- `usage.{input_tokens, cache_read_tokens, cache_hit_pct, usage_source}`
- `categories[]`（12 类，含 `recorded`/`tokens`/`share`/`count`/`top_item`）
- `groups[]`（5 个展示组）
- `series[]`（每次模型调用的 input tokens）
- `insights[]` / `headline`
- `method`（数据源与估算口径）

完整 schema 见 `references/report-schema.md`；适配细节见 `references/harness-adapters.md`。

## 素材

`assets/` 里已经包含当前版本的主视觉素材：

- `hero-bento.jpg`：鲸鱼娘趴在便当盒后的主视觉
- `avatar.png`：从主视觉裁出的头像，保证神态一致
- `icon-tools.png` / `icon-reason.png` / `icon-defs.png` / `icon-skills.png` / `icon-pearl.png`：从图标表裁出的透明 PNG

`assets/manifest.json` 记录 asset id、来源项目、模型和裁切说明。需要重生成时运行 `bootstrap-assets --explicit --run`；它需要 IARTStudio 正在运行，并以 `鲸鱼娘专用` 项目里的 chibi 参考图为锚点。

## 隐私

- 报告只包含聚合值、工具名、字符数、截断后的命令/路径摘要；不转储消息正文。
- 默认不把任何用户输入或工具输出原文写进 HTML/JSON。
- 会话日志可能包含敏感信息；`context-report.json` 只保留统计字段。

## 版本

`0.0.4`。版本同时写在 `VERSION`、`skill.json` 和 `context-report.json` 的 `tool_version` 里。
