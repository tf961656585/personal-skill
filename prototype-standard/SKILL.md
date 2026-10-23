---
name: prototype-standard
description: |
  原型（prototypes/ 目录下的零构建 HTML 交互原型）开发制作标准与文件 Schema，跨项目通用。
  当需要创建原型、新建原型页面、修改或重构既有原型、把原型内联代码拆分为独立文件、
  向 prototypes/shared/ 下沉共享实现、编写原型演示数据、做原型验收或巡检、在新项目初始化
  原型体系时触发。用户提到"原型规范"、"原型标准"、"原型 Schema"、"原型怎么组织"、
  "原型拆分"、"下沉 shared"、"prototypes"、"HTML 交互原型"、"交互 demo 页"相关工作时
  必须先读本 skill 再动手。不可逆决策（契约/边界/状态所有权）不适用本 skill，走 spec/ADR。
---

# 原型开发制作标准（跨项目通用）

本 skill 承载 HTML 交互原型的唯一工程结构标准，适用于任何项目的 `prototypes/` 目录（或等价
原型目录）。原型是**可运行的设计决策载体**（可逆决策的验收物），其可维护性等于决策可读性：
验收者要能在每个文件里一眼看清"这段在验证什么"。本标准的目标是让原型**更便宜更好读**，
不是把原型生产化——所有约束都是零工具链的纯纪律。

## 0. 两层结构：通用规则在 skill，项目事实在投影

本 skill 跨项目复用，靠两层分工避免"通用规则"与"项目实例"互相污染：

- **通用层（本文件）**：目录 Schema、职责矩阵、装配契约、下沉规则、预算默认值——任何项目
  不加修改即可执行；
- **项目层（项目投影文件 `prototypes/README.md`）**：本项目对通用标准的实例化事实——令牌
  文件名、shared 文件清单与装配序、巡检命令、lint 接线位置、预算覆盖、决策回写去向。
  模板见本 skill `references/overlay-template.md`。

单一事实源纪律：通用规则只在 skill，项目事实只在投影。投影文件禁止复制通用规则（漂移源），
本 skill 不硬编码任何具体项目的文件名（碰到的项目特例一律查投影）。

## 1. 动手前第一步：读项目投影

进入任何原型工作（新建/修改/重构/下沉/验收/巡检）前，先读该项目的 `prototypes/README.md`：

- **存在** → 其中记录的实例化事实优先于本 skill 的通用默认值（默认名、默认装配序、默认命令）。
- **不存在** → 按本 skill 默认值执行；若该项目目录里确有原型或即将开始原型工作，按第 11 节
  初始化投影文件后再动手（首个原型建立时就写投影，不要拖到"以后补"）。

## 2. 目录结构 Schema

```
prototypes/
├── README.md                  # 项目投影（实例化事实，见第 0/1 节）
├── shared/                    # 跨原型单一事实源（≥2 个原型实际消费才准入）
│   ├── tokens.css             # 令牌唯一定义点（通用默认名；项目用别名记投影）
│   └── <共享件>.css/.js       # 外壳 / 组件 / 域级文件组，按第 6 节形态组织
└── <原型名>/                   # kebab-case 命名
    ├── index.html             # 纯结构 + 装配（必有）
    ├── style.css              # 页面私有样式（内联 style 一律禁止，故必有）
    ├── data.js                # 演示数据（≥100 行或多张注册表才独立成文件）
    ├── app.js                 # 渲染 + 交互 + 初始化（必有，必须最后加载）
    └── <域>.js                # app.js 超预算时按职责域拆出：refs / params / task / preview / scenarios…
```

原型目录下的文件角色名（index.html / style.css / data.js / app.js）是通用契约，巡检脚本按
这些名字检查加载顺序，不要改用别的名字；域文件命名自由。

## 3. 文件职责矩阵

| 文件 | 只承载 | 禁止 |
|---|---|---|
| index.html | 语义骨架、`<link>`/`<script src>` 装配、头部导航注释（本原型验证什么、上游 spec 锚点、文件清单与加载职责） | 任何 `<style>`/`<script>` 内联体、inline 事件属性（onclick= 等） |
| style.css | 页面私有结构与状态样式 | 重定义 shared 令牌、硬编码 hex |
| data.js | 注册表、场景预设、文案、决策条目；转录自 spec 的数据必须注释上游文档与日期 | DOM 访问、事件监听 |
| 域文件 / app.js | 渲染、事件绑定、与 shared 模块的胶水；app.js 入口唯一（文件末尾初始化） | 定义演示数据 |

## 4. 分层与依赖方向（必须单向）

```
令牌层      tokens.css 的 :root / 主题变量
   ↑ 只消费令牌，不得感知任何具体原型
共享件层    shared/*.css 结构段 + *.js 模块
   ↑ 纯数据，不触 DOM
页面数据层  data.js
   ↑ 消费以上全部，最后加载
页面行为层  域文件 → app.js
```

原型之间禁止互相引用文件。跨原型共享只有一条路：下沉 shared（见第 8 节）。

## 5. 装配契约（加载顺序即依赖顺序）

- **零构建是特性**：只用 classic `<script src>` 与 `<link>`，保证 file:// 双击直开——验收者
  不装任何东西就能打开原型。跨文件共享绑定靠 classic script 全局词法环境（前文件顶层
  `const`/`function` 对后文件可见），**加载顺序即依赖顺序**。
- 样式装配序：令牌 css → 其他 shared css（按项目投影记录的顺序）→ 页面 `style.css`。
- 脚本装配序（body 末尾）：shared JS（组件级在前；域级文件组按 data → 各域 → core 内聚
  顺序，core 组末）→ `data.js` → 页面域文件（被依赖者先行）→ `app.js`（最后）。
- 页面 JS 消费 shared 全局（shared 模块挂到 `window` 的命名空间）时，文件头必须声明
  `/* global XxxChrome */`——不声明会被 ESLint `no-undef` 拦截。
- 跨文件消费的顶层绑定（如 data.js 的注册表常量）在定义文件用 `/* exported NAME */` 声明；
  被后置文件读写的绑定在消费文件用 `/* global name */`（需赋值时 `/* global name:writable */`）。
  这套指令依赖项目为 `prototypes/**/*.js` 配置的 ESLint 作用域块（`sourceType: "script"` +
  关闭 next 预设注入的 `ecmaFeatures.globalReturn`——该选项会破坏 `/* exported */` 生效 +
  用基础 `no-unused-vars` 替换 TS 版）。项目没配 ESLint 时协议仍然遵守（可读性价值独立于
  lint），只是没有机器检查；配置块模板见第 11 节。改动该块前先验证指令仍生效
  （`npx eslint prototypes/ --max-warnings=0`）。
- 域文件只定义函数与自身状态，不得有引用 app.js 绑定的顶层立即执行语句；需要立即接线
  （init、addEventListener、shared 模块 init 调用）的语句一律放 app.js。

## 6. 封装约定

- 跨原型共享的核心规则：**凡共享且自身带 DOM 结构的产物，结构定义必须在 shared**，消费
  原型的 index.html 只留挂载点，不复制结构。这条规则消除"样式行为下沉了、HTML 骨架各原型
  复制"的半下沉——复制结构没有权威定义，改一处漏一处只是时间问题。按共享粒度分两类形态
  （均为正类，按判据选择）：
  - **组件级**——判据：各宿主 DOM 结构各异，宿主差异可经 `init(cfg)` 回调注入隔离（典型：
    节点选中态 chrome、dock 拖拽骨架）。形态：一文件一命名空间（IIFE 挂 `window.<Name>`），
    自带结构时组件内含模板串，不自动初始化。
  - **域级**——判据：消费原型共享同一 DOM 结构契约（相同骨架与 id），差异只在场景演示与
    提交后行为（典型：多原型共用的 dock 底座文件组，由原型间继承链长出）。形态：文件组——
    多文件沿用 classic script 全局词法环境（与第 5 节页面文件同一机制）；跨文件绑定走
    `/* exported */`（定义侧）/`/* global */`（消费侧）协议；组内恰有一个 core 文件（组末），
    **骨架由 core 注入**（提供 `mountXxx(container)` 生成共享 DOM 结构，DOM 契约即 core
    本身，不靠消费方 HTML 手工对齐），core 之外的组内文件不得有顶层接线。组内单文件仍受
    shared 预算约束。新消费方接入路径：挂载点装配 + 自写场景域；契约不够用时先裁定契约
    演进（改 core 并同步全部消费方），不得在原型内另起第二套。
- shared 文件头四段式：① 定位与单一事实源声明 ② 设计依据（决策编号或上游 spec 锚点）
  ③ 消费方式（API 签名或装配序） ④ 同步义务（"消费原型不得另起第二套实现"）；下沉收口的
  分歧写入「裁定记录」段。
- 交互控件必须带 aria 属性；默认 `<html data-theme="light">`（明暗主题变量集由令牌文件定义）。

### 叠层对比度工具

设计涉及玻璃 / 磨砂 / 浮层压暗 / 渐变上的文字时，用 `references/contrast-stack.mjs` 核验 WCAG 对比度；用法与边界见 `references/contrast-stack.md`。脚本只算给定叠层的对比度，项目的最坏栈配方由项目投影记录。

## 7. 大小预算（重构触发线，不是豁免申请理由）

| 项 | 预算 | 超线动作 |
|---|---|---|
| index.html | ≤ 500 行 | 把样式/数据/行为拆出去 |
| 页面单 CSS / JS 文件 | ≤ 600 行 | 按职责域再拆 |
| shared 单件 | ≤ 800 行 | 按域拆多件 |
| 单个函数 | ≤ 80 行 | 拆子函数 |

预算是通用默认值，项目可在投影中收紧（不可放宽到失去约束力）。若项目另有行数硬门禁
（如仓库级 guard），它是兜底；本节预算严于它，由巡检脚本执行（第 10 节）。

## 8. 共享下沉规则（两处即沉）

- 同一产物出现**第二个消费者之前**必须下沉 shared，先沉再用。产物口径 = 结构（HTML 骨架）/
  样式 / 行为 / 数据 / 文案——任何一项都不允许"部分下沉"（如样式行为下沉了、HTML 骨架各
  原型复制）。禁止"复制 → 漂移 → 事后收口"。
- 下沉时两原型实现不一致的分歧必须收口为单一实现，裁定记入 shared 文件头「裁定记录」段。
- 只有一个消费者时留在页面内，shared 不收孤儿。

## 9. 演示数据纪律与决策可读性

- 转录自上游 spec / 接口文档的数据必须在 data.js 注释标注上游文档与转录日期。
- 决策记录条目数据放 data.js（可 diff、可审查），原型内以抽屉/面板呈现；场景演示按钮驱动
  （演示①②③…），让验收者一键到达要拍板的现场。
- 原型验收拍板的不可逆决策（契约/边界/状态所有权）必须回写 spec/ADR（回写去向记项目
  投影）；原型退役前完成回写。

## 10. 巡检（不进硬门禁）

```bash
node <本 skill 目录>/scripts/prototype-audit.mjs <项目根>   # 项目投影记录了包装命令时优先用包装命令
```

检查：index.html 无内联 `<style>`/`<script>` 体；无 inline 事件属性；行数预算（500/600/800）；
原型文件不引用兄弟原型目录；`<script src>`/`<link>` 引用的本地文件存在；加载顺序契约
（data.js 先于 app.js、app.js 最后）；非令牌 CSS 的硬编码 hex（warning 级）。令牌文件名经
`--tokens <文件名>` 指定，未指定时自动探测（`tokens.css` / `node-prototype.css`）。

巡检是主动卫生手段，不作为交付放行门禁；违例按本 skill 修复。

静态巡检之外另有两个运行时验证脚本（同样不进硬门禁）：

```bash
node <本 skill 目录>/scripts/prototype-page-sweep.mjs [--base <http 基址>]
```

加载 `prototypes/` 下每个 `*/index.html`，收集 `pageerror` 与 `console.error`——改
`prototypes/shared/*` 共享脚本后的破坏面巡检（共享实现被多少原型页消费，就得扫多少页）。
`--base` 缺省用 file:// 直开（Playwright 库支持；仅 playwright-cli 拦 file://）。
任一页报错退出码 1。

交互行为断言（点击链路、选中态、联动文案、界面禁用词扫描）复制 `scripts/prototype-dom-smoke.template.mjs`
到 /tmp 按目标原型填断言：只断言 DOM 文本/属性/计算值（主线程无视觉、禁截图）；
`aria-disabled` 件用 `dispatchEvent("click")` 触发（locator.click 会被可操作性检查拒绝）。
两者分工：sweep 管"有没有报错"，模板管"行为对不对"。

两个脚本共用 `scripts/chromium-launch.mjs` 启动浏览器：先按 playwright 自己的 revision 启动，
失败则回退到 `ms-playwright` 缓存中已装的 chromium。这是为了免掉"playwright 版本要求的
revision 与本机缓存不一致 → 硬失败 → 必须联网 `npx playwright install`"这条常见卡点——
纯本地已有缓存时不该被逼着下载。回退发生时会打印一行说明实际用了哪个可执行文件，
避免"这次为什么跑得起来"无从追溯。

## 11. 新项目初始化（bootstrap）

在一个没有原型体系的项目里第一次做原型时：

1. `mkdir -p prototypes/shared`，创建 `prototypes/shared/tokens.css`：`:root` 浅色变量集 +
   暗色主题变量集，头部按四段式声明"令牌唯一定义点"。
2. 复制本 skill `scripts/prototype-audit.mjs` 到项目脚本目录（建议 `tooling/scripts/`），
   package.json 加 `"prototype:audit": "node ./tooling/scripts/prototype-audit.mjs"`。
   脚本副本以项目内为事实源（保证仓库自洽、协作者无障碍运行）；skill 内 master 更新后
   可选同步，同步义务记入投影。
3. （可选，项目用 ESLint flat config 时）为 `prototypes/**/*.js` 加作用域块：
   ```js
   { files: ["prototypes/**/*.js"],
     languageOptions: { sourceType: "script",
       parserOptions: { ecmaFeatures: { globalReturn: false } } },
     rules: { "no-unused-vars": ["warn", { argsIgnorePattern: "^_",
       varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" }] } }
   ```
   （若项目用 TS 版 no-unused-vars，需在该块内关闭 TS 版、启用基础版——TS 版不支持
   `/* exported */`。）项目没有 ESLint 时跳过，巡检脚本不依赖 ESLint。
4. 从 `references/overlay-template.md` 起步写 `prototypes/README.md` 项目投影。
5. 第一个原型按第 2 节 Schema 起步。此时 shared 目录只有令牌文件是合法状态——共享件
   等第二个消费者出现再下沉（第 8 节），不要预防性下沉。

## 12. 既有原型改造步骤（retrofit recipe）

1. `<style>` 体整段搬到 `style.css`，原位换 `<link rel="stylesheet" href="style.css">`
   （排在 shared 之后）。
2. 内联 `<script>` 体按第 2 节拆为 data.js / 域文件 / app.js；先拆数据（注释分段里
   "注册表/工厂/表"段），行为按既有注释分段归域。
3. 拆分时**只搬移不改写**；搬移后扫描域文件中的顶层立即执行语句，全部集中到 app.js。
4. index.html 头部导航注释更新文件清单。
5. 验证：`node --check` 每个新 JS 文件 → `npx eslint prototypes/ --max-warnings=0`
   （配了 ESLint 时）→ 巡检命令 → 浏览器打开核心交互冒烟（file:// 直开）。

## 13. 已知坑（classic script 全局词法环境）

- **同名顶层声明双声明即 SyntaxError**：文件组共享全局词法环境，一个顶层 `let/const` 名
  只能在一个文件声明，第二个文件再声明同名直接 SyntaxError、页面全白（`node --check` 单
  文件查不出，因为是跨文件冲突）。新增跨文件共享变量前先 grep 确认唯一声明点。
- **顶层立即执行语句引用后加载文件的绑定 → ReferenceError**；函数体内的运行时引用合法
  （调用时被引用文件的词法绑定已存在）。所以第 5 节要求顶层接线一律放 app.js。
- `/* exported */` / `/* global */` 协议依赖 ESLint 块配置正确；改动 lint 配置后用
  `npx eslint prototypes/ --max-warnings=0` 验证指令仍生效。
- file:// 直开没有 dev server 容错：引用路径层级或大小写错了直接白屏。巡检脚本的断链
  检查就是为此存在的，改装配后必跑。

## 14. 禁止项汇总

内联 `<style>`/`<script>` 体；构建链、打包器、npm 依赖、框架、ES modules / import map；
原型间互相引用；复制 shared 实现另起第二套；硬编码 hex（颜色只经令牌文件消费）；inline
事件属性。
