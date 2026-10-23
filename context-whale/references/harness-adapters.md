# Harness Adapters · v0.0.4

核心原则：**报告 schema、洞察规则、HTML 渲染器共用；只有“从哪里读、能读到什么”按 harness 适配。**

| Harness | 数据源 | 真实 usage | system prompt | tools schema | tool results | fidelity |
|---|---|---|---|---|---|---|
| ZCode | `~/.zcode/cli/db/db.sqlite` + `~/.zcode/cli/rollout/model-io-*.jsonl` | 每次调用 | ✅ | ✅ | ✅ | **L1** |
| DeepSeek Harness | `~/.dsh/sessions/<encoded-cwd>/*/session.v*.jsonl.zstd`（v3 / v4） | 每次调用 | ✅ `system/message` | ✅ `request/header.tools` | ✅ `tool/result` | **L1** |
| Claude Code | `~/.claude/projects/<encoded-cwd>/*.jsonl` | 每条 assistant | ❌ | ❌ | ✅ | **L2** |
| Codex / ChatGPT app | `~/.codex/thread_history_1.sqlite` + `state_5.sqlite` | 线程累计 `tokens_used` | ❌ | 仅 dynamic tools | ✅ `commandExecution.aggregatedOutput` | **L2** |
| Pi / OpenClaw | `~/.openclaw/agents/main/sessions/*.jsonl` / `~/.pi/sessions` | 每条 message | ❌ | ❌ | ✅ | **L2** |

## 各适配器要点

### ZCode

- 会话表 `session` 里按 `directory = cwd`、`parent_id is null`、`task_type = 'interactive'` 取最近一条。
- rollout 每行是 `model_io`；`request.messagesKind` 可能是 `full` 或 `tail`：
  - `full`：完整消息数组，直接作为基线。
  - `tail`：只存最后 64 条，带 `messageOffset`；从基线追加 `messages[len(ctx)-offset:]`。
  - **必须过滤 `querySource == "session_title"`**：标题生成调用只有 2 条消息，会把基线打回 2，导致后续 tail 重建失败。
- 类别：
  - system → `system_prompt`
  - user 里的 `<system-reminder>` 按技能清单/子代理清单/日期/其他拆分
  - assistant content blocks：`reasoning` / `text`
  - assistant `toolCalls` → `tool_calls`
  - role `tool` → `tool_results`
- 窗口上限：从 `~/.zcode/v2/provider_config.json` 递归查找匹配 `modelId` 的 `config.properties.contextWindow`。
- 已知问题：旧版 CLI 的 `task get` 不返回 `warnings`；本 skill 不依赖它。

### DeepSeek Harness

- 会话文件是 zstd 压缩的 JSONL 事件流；用 `zstd -dc` 解压。
- 关键事件：
  - `request/header` → `data.header.tools`
  - `request/context` → `data.contextWindow`
  - `system/message` → `data.message.content`
  - `user/message` → `data.content`
  - `assistant/message` → `data.message.content`（`reasoning` / `text` / `tool-call`）+ `data.usage`
  - `tool/result` → `data.message.content[].content`，用 `toolCallId` 回查工具名
- 忽略 `agent/inbox/spliced`，避免和 `user/message` 重复计数。

### Claude Code

- JSONL transcript：
  - `user` → `message.content`（字符串或 `tool_result` / text blocks）
  - `assistant` → `thinking` / `text` / `tool_use`；`message.usage` 提供 `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`
  - `attachment.skill_listing` → `injection_skills`
- **系统提示和工具 schema 不在 transcript 里**，因此 `coverage.system_prompt=false`、`coverage.tool_definitions=false`。
- 上下文窗口按模型名假设：含 `1m` → 1,000,000，否则 200,000；报告标注 `source: assumed_model_limit`。

### Codex / ChatGPT app

- `state_5.sqlite` 的 `threads` 提供 cwd/model/`tokens_used`。
- `thread_history_1.sqlite` 的 `thread_items` 提供：
  - `userMessage` / `agentMessage` / `reasoning`
  - `commandExecution.command` + `aggregatedOutput`
  - `fileChange` / `webSearch` / `mcpToolCall` / `dynamicToolCall`
  - `contextCompaction`
- `thread_dynamic_tools` 只覆盖动态工具，不是内置工具的完整 schema。
- **`tokens_used` 是线程累计值**，不是当前上下文；当前上下文的 token 数按 item 字符量估算，报告写 `usage_source: estimated`。

### Pi / OpenClaw

- 读取 `~/.openclaw/agents/main/sessions/*.jsonl`（以及 `~/.pi/sessions`）。
- 每行 `type=message`，`message.role` / `content` / `usage`。
- 只支持有 `cwd` 的会话；没有 system/tools，fidelity 为 L2。
- 如果本机没有 Pi 的真实落盘格式，adapter 会返回空；用 `--session <path>` 显式指定一个 JSONL 再试。

## 数据缺失时的行为

- `categories[].recorded=false`，`tokens/share` 为 `null`，HTML 显示「未记录」。
- 固定开销洞察只在 `tool_definitions` 和 `system_prompt` 都可用时触发。
- 窗口上限未知时只显示绝对 tokens，不显示百分比。
- 渲染头始终显示 `harness / fidelity`，让用户知道这份报告能信到什么程度。
