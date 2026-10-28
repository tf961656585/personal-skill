# 验证与取证配方

适用：`SKILL.md` 提到的具体命令与平台细节。规则在 `SKILL.md`，本文件只放可复制的操作步骤；换了技术栈时按等价手段替换，不要把示例参数当成通用规则。

## 1. 无测试设施时的渲染验证（以 React/TSX 为例）

目标：不引入测试设施，拿到可逐条比对的确定性输出。

```bash
./node_modules/.bin/esbuild <entry>.tsx --bundle --platform=node --format=cjs \
  --jsx=automatic --outfile=/tmp/render-check.cjs && node /tmp/render-check.cjs
```

- **必须 `--format=cjs`**：esm 输出会因 react-dom 这类 CJS 包的互操作报 `Dynamic require of "stream" is not supported`。
- entry 是临时工件，验证完即删、不留在 `src/`——没有测试设施承载它，留着会让下一轮误以为有回归保护。
- 适合断言两类契约：结构与文案的逐字/结构化比对；破损输入不抛异常（未闭合标记、空输入、被拒的非法地址）。
- 浏览器侧核验优先做结构化读取（取 `outerHTML` / 文本逐项比对）而非截图；截图只用于组织人工验收材料。
- **版式结论断言不了**：字号、视觉层级、间距是否成立，只有看真实渲染才知道。这类结论不归 agent 判：附截图与「重点看哪几处」交用户验收（visual-handoff）。
- 其他技术栈用等价的服务端渲染或 DOM 解析；不要为了套这条命令引入构建链。

## 2. 长链路分段计时

怀疑某条多段链路（预飞、构建链、发布链）整体慢时，先用分段计时脚本量出每段耗时再定位优化点。链模式（`:::` 分隔各段，失败段标 FAIL 并带非零退出码）：

```bash
~/.agents/skills/implementation-discipline/scripts/time-command-chain.sh run /tmp/chain.log \
  pnpm build:typecheck-deps ::: pnpm typecheck:workspaces ::: pnpm lint
~/.agents/skills/implementation-discipline/scripts/time-command-chain.sh parse /tmp/chain.log
```

- 优化前后各跑一轮（必要时冷/热缓存各一轮），用同一段清单对比，拿数字说话。
- 复杂脚本内嵌用库模式：`source` 后调 `step <名称> <命令...>`，日志默认 `/tmp/chain-timing.log`，可用 `CHAIN_TIMING_LOG` 改；库模式不自动清空日志，调用方自行截断。
- 用法与日志格式详见脚本头注释：`scripts/time-command-chain.sh`。

## 3. 门禁报红基线对比

先导出改动前源码树，跑同一条门禁，比较失败行与数字：

```bash
git archive HEAD | tar -x -C /tmp/<name>            # 改动前源码树，只读导出（不碰工作区、不动 .git）
ln -s <repo>/node_modules /tmp/<name>/node_modules  # 复用依赖（子目录工程软链到对应包目录）
cd /tmp/<name> && <同一条门禁命令>
```

- 两边失败行与数字逐位相同即判定存量红，与当轮改动无关——比 `git stash`（要写工作区、有丢改动风险）和「读代码推断没影响」（无证据）都可靠；副本在 `/tmp`，跑完即弃。
- 归属未判定前不要动代码「修红」——把存量红当成本轮引入，最容易改坏与本次任务无关的数值或校验。
- 上报形态（对象业务名 + 类型 id、实配值 vs 下限、数值出处）见 `SKILL.md`「门禁报红的归属判定」。

## 4. 状态变更命令的 macOS 细节

- 终止进程、删除文件后，不能凭单一快照字段下结论：内存高压下 RSS 与实际占用严重脱节，页面被压进 swap/压缩区会造成「已清理」假象。以目标确实消失、指标确实回落为准。
- 沙箱化 shell 拒绝 `kill`/`pkill`（Operation not permitted）时，显式提权重试，不换花样绕过；清理失控进程属正当场景。
- macOS 上 `PPID==1` 不等于孤儿——GUI 应用合法挂在 launchd 名下；甄别孤儿须「进程名特征 + `PPID==1`」双条件，禁止见 Electron/node 就杀。
