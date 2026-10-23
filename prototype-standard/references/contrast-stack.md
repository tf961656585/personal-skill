# 叠层对比度核验（contrast-stack）

设计涉及玻璃、磨砂、浮层压暗、图上角标、渐变上文字时，用本工具核验 WCAG 对比度，不靠目测：

```bash
node "$HOME/.agents/skills/prototype-standard/references/contrast-stack.mjs" <前景hex> <基底hex> [层:hex:alpha ...]
# 层从远到近依次叠放。示例：白字压在 60% 白玻璃 + 深蓝底上
node "$HOME/.agents/skills/prototype-standard/references/contrast-stack.mjs" '#ffffff' '#1c3d5a' '#ffffff:0.6'
```

输出合成背景亮度、对比度与 WCAG 等级（AAA / AA正文 / AA大字 / 不达标）。

## 边界

- 只算**给定叠层**的对比度；各项目的最坏栈配方（哪些环境层参与叠加、各自 alpha）由项目投影记录，调用时按配方传参。
- 底线类决策（如"透明度不得低于 X"）以脚本数字为依据，不用估计值。
- 这是设计决策工具，不是视觉验收；观感与整体调性仍归用户判定（见 visual-handoff skill）。
