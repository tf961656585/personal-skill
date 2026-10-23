# Context Report Schema · v0.0.4

`context-report.json` 是稳定输出，供后续趋势分析。顶层字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 报告 schema 版本，当前 `1.0` |
| `tool_version` | skill 版本，当前 `0.0.4` |
| `generated_at` | 生成时间 |
| `harness` | `zcode` / `dsh` / `claude_code` / `codex` / `pi` |
| `fidelity` | `L1` 完整请求 / `L2` 会话级 / `L3` 仅转写 |
| `session` | `{id, path, model, updated, cwd}` |
| `window` | `{limit, used, pct, source}`；`limit` 未知时为 `null` |
| `usage` | `{input_tokens, cache_read_tokens, cache_hit_pct, usage_source, thread_cumulative_tokens}` |
| `categories[]` | 12 类明细，见下 |
| `groups[]` | 5 个展示组 |
| `series[]` | 每次模型调用的 input tokens |
| `insights[]` | 3 条确定性建议 |
| `headline` | 一句话结论 |
| `coverage` | 各数据面是否可用 |
| `method` | 数据源与估算口径 |

## categories[]

```json
{
  "key": "tool_results",
  "label": "工具结果",
  "recorded": true,
  "tokens": 51835,
  "share": 0.464,
  "count": 52,
  "top_item": {"tool_name": "Bash", "chars": 26030, "tokens_est": 8127}
}
```

- `recorded=false` 表示该 harness 没有落盘这一类；`tokens`/`share` 为 `null`，渲染为「未记录」，不能当 0。
- `tokens` 是估算值，按真实 `usage.input_tokens` 校准；`share = tokens / known_total`。
- `top_item` 只给工具结果/工具定义等类别，且只保留工具名、字符数、条数，不保留正文。

## groups[]

| key | label | 包含类别 |
|---|---|---|
| `tool_results` | 工具结果 | `tool_results` |
| `assistant_reasoning` | 助手思考 | `assistant_reasoning` |
| `tool_definitions` | 工具定义 | `tool_definitions` |
| `rest` | 调用与注入 | `tool_calls`、skills/agents/date/other 注入、`system_prompt`、`assistant_text`、`other_blocks` |
| `user_input` | 你的话 | `user_input` |

## coverage

```json
{
  "system_prompt": true,
  "tool_definitions": true,
  "tool_results": true,
  "usage": "per_call",
  "full_request": true
}
```

- `system_prompt` / `tool_definitions` 可能是 `false`（harness 不落盘）或 `"partial"`（只记录动态工具）。
- `usage` 取值：`per_call` / `cumulative` / `estimated`。

## 口径

- 总量：模型返回的真实 `usage.inputTokens`（L1）或最后一条 assistant usage（部分 L2）。
- 分类占比：按各段字符量（中文≈1 token/字，其余≈3.6 字符/token）估算，再按真实总量校准。
- Codex 的 `tokens_used` 是线程累计值，不是当前上下文；报告把它放在 `usage.thread_cumulative_tokens`，不作为 `window.used`。
- 缓存命中 = `cache_read_tokens / input_tokens`；它降低费用，不减少上下文长度。
