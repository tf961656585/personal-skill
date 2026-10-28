# 项目投影模板（prototypes/README.md）

> 用途：新项目初始化原型体系时，复制本模板为该项目的 `prototypes/README.md` 并填实。
> 本文件只承载该项目对 prototype-standard skill（user 级，通用标准）的**实例化事实**；
> 通用规则（目录 Schema、职责矩阵、下沉规则、预算默认值）以 skill 为唯一事实源，禁止在此复制。
> 未填的分节删除；项目没有对应事实的（如未配 ESLint）整节删除。

---

# prototypes/ 项目投影

## 令牌文件

- `prototypes/shared/<令牌文件名>.css` —— 令牌唯一定义点（:root 浅色 + 暗色主题集）。
  巡检 hex 检查以它为白名单文件。主题切换机制与变量命名约定（如有）一句话说明。

## shared 文件清单

| 文件 | 形态（组件级/域级/CSS） | 角色 | 消费方式 |
|---|---|---|---|
| tokens.css | CSS | 令牌唯一定义点 | `<link>` 第一个加载 |
| … | | | |

（域级文件组在此列全组成员与组内顺序。）

## 标准装配序

- 样式：`<令牌 css>` → `<其他 shared css 按序>` → 页面 `style.css`。
- 脚本（body 末尾）：`<shared JS 按序，组件级在前，域级组 core 组末>` → `data.js` → 域文件（被依赖者先行）→ `app.js`。
- 页面 JS 消费的 shared 全局命名空间：`/* global Xxx, Yyy */`。

## 巡检命令

```bash
<如 pnpm prototype:audit / node ./tooling/scripts/prototype-audit.mjs>
```

- 脚本位置：`<路径>`（项目内副本，项目事实源）。
- master 同步义务：skill 内 master 更新后可选同步；最近同步日期 `____`。
- 令牌文件如非候选名（tokens.css / node-prototype.css），在此记录 `--tokens <文件名>` 用法。

## lint 接线

- `<如 eslint.config.mjs 的 prototypes/**/*.js 作用域块>`——`/* exported */` / `/* global */`
  协议依赖此块；改动前验证：`npx eslint prototypes/ --max-warnings=0`。

## 预算覆盖（可选）

- `<仅当项目收紧预算时记录；未覆盖则删除本节，用 skill 默认 500/600/80>`

## 决策回写去向

- 原型拍板的不可逆决策回写：`<如 docs/spec/、docs/adr/；有尾检查工具的注明>`。

## 本项目原型清单

- `<原型名>` —— 一句话说明验证什么（详细：各 index.html 头部导航注释）。
