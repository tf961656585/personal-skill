# Personal Skills

一组面向 AI coding agent 的工作流 skill，覆盖需求裁决、设计分层、实现纪律、交付验收、测试治理、失效表示治理与上下文可视化。

每个目录都是一个独立的 skill，核心文件为 `SKILL.md`；部分 skill 带有 `references/`（细则）、`scripts/`（可执行工具）或 `assets/`（静态素材）。

## Skill 一览

| Skill | 用途 |
|---|---|
| `clarification-spiral` | 澄清螺旋：苏格拉底式追问框架，把模糊表述提炼成清晰、可执行的真实需求 |
| `context-whale` | 仅显式 `/context-whale` 调用：读取本机会话记录，把上下文窗口构成渲染成便当图报告，并输出可分析 JSON |
| `decision-question` | 提交待决策项时的写作规范：每个裁决点自带完整上下文链，用用户能懂的语言写出 |
| `delivery-check` | 交付前门禁清单：确认主链、单一实现、残留、测试、设计同步证据、行为验收与视觉交接 |
| `design-guide` | 设计层入口：判定可逆性、选择载体，并路由到 spec / ADR / 原型 / 设计文档 / 流程图 |
| `design-review` | 多份设计产物之间的自洽性审查：断链、契约矛盾、职责重叠、术语漂移 |
| `implementation-discipline` | 实现与重构纪律：职责归属、主抽象复用、唯一版本、门禁裁定、依赖与验证命令 |
| `master-subagent` | 主从 agent 协作规范：拆解、委派、验收、汇总，子 agent 在独立上下文返回蒸馏结论 |
| `mermaid-business-flowchart` | 用 Mermaid 流程图把业务需求转化为可评审、可落盘的流程协议 |
| `playwright-env` | 本机 Playwright 环境口径：npm 全局链路、浏览器池保护、升级重置与排障 |
| `problem-triage` | 问题分诊与重构信号判断：何时停止打补丁改做重构、如何对待用户给的具体实例 |
| `product-context` | 默认对外表述规范：把仓库状态翻译成产品行为、影响与待办（默认读者是产品经理） |
| `project-entry` | 项目入口与文档地图，含 `memory/` 读协议与设计基准回执 |
| `prototype-standard` | 零构建 HTML 交互原型的开发标准、文件 Schema、审计与巡检脚本 |
| `reflect` | 会话级反思与跨会话记忆沉淀，仅在显式调用时使用 |
| `repo-hygiene` | 仓库级周期卫生巡检：机制失灵与产物失管的存量扫描，输出分级报告交用户裁决 |
| `spec-guide` | Spec / ADR / 契约文档的编写、单份质量审查与维护，含一致性校验脚本 |
| `stale-representation` | 变更继承面协议：找出改动后失效的第二事实源（文档、注释、prompt、配置、mock、索引、外部假设）并逐项处置 |
| `sweep` | 任务收尾扫描：清理会被后续上下文误当成事实的残留 |
| `test-linkage` | 测试与 spec 的程序化关联，以及孤儿、沉睡、过时测试的治理 |
| `ui-copy-check` | UI 文案的用户视角守卫：空态、错误 / 成功提示、按钮、引导语、提示气泡 |
| `visual-handoff` | 视觉交付与人工验收规范：agent 只做程序化检查，视觉通过权交给用户 |

## 安装

把需要的 skill 目录链接到 harness 的 skills 目录即可。以 ZCode / Claude Code 常见的 `~/.agents/skills` 为例：

```bash
git clone https://github.com/tf961656585/personal-skill.git
cd personal-skill

# 链接单个 skill
ln -s "$PWD/spec-guide" ~/.agents/skills/spec-guide

# 或链接全部
for d in */; do
  ln -s "$PWD/${d%/}" ~/.agents/skills/"${d%/}"
done
```

不同 harness 的 skills 目录可能不同（例如 `~/.claude/skills`、`~/.codex/skills`），按实际环境调整。已存在同名目录时先确认再替换，避免覆盖。

## 依赖

大部分 skill 只依赖 agent 本身，无需额外安装。少数带脚本的 skill 有可选依赖：

- `context-whale`：Python 3；重新生成图片素材时需要 Pillow 与正在运行的 IARTStudio。
- `prototype-standard`：Node.js；页面巡检脚本使用 Playwright。
- `spec-guide` / `test-linkage` / `reflect`：Python 3。

脚本缺失依赖时会给出提示，不影响 skill 的说明性内容。

## 隐私说明

- 所有 skill 都在本地运行，不包含 API Key、Token 或任何凭据，也不会把数据上传到外部服务。
- `context-whale` 会读取本机的 harness 会话记录（如 `~/.zcode`、`~/.claude/projects`、`~/.codex`）用于统计上下文构成；输出只写入你指定的目录。
- `context-whale/data/history.jsonl` 是运行时生成的本地统计历史，已加入 `.gitignore`，不会进入版本库。

## License

[MIT](LICENSE)
