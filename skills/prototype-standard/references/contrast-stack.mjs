#!/usr/bin/env node
// 叠层对比度测算：给定前景、基底色与若干半透明叠层（从远到近），输出合成后
// 的 WCAG 对比度与达标等级。适用于玻璃/半透明材质底线、浮层压暗、图上角标、
// 渐变上文字等任何「文字压在多层 alpha 合成背景上」的场景。
// 注意：本脚本只算「给定叠层」的对比度；各项目自己的最坏栈配方（哪些装饰层
// 参与叠加及各自 alpha）由项目自行记录，调用时按配方传参。
// 用法：node contrast-stack.mjs <前景hex> <基底hex> [层:hex:alpha ...]
//   示例（白字压在 60% 白玻璃 + 深蓝底上）：
//   node contrast-stack.mjs '#ffffff' '#1c3d5a' '#ffffff:0.6'
const toRgb = (h) => {
  const n = parseInt(h.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const over = (top, a, bot) => top.map((c, i) => c * a + bot[i] * (1 - a));
const contrast = (a, b) => {
  const [hi, lo] = lum(a) > lum(b) ? [lum(a), lum(b)] : [lum(b), lum(a)];
  return (hi + 0.05) / (lo + 0.05);
};
const [fg, base, ...layers] = process.argv.slice(2);
if (!fg || !base) {
  console.error("用法: node contrast-stack.mjs <前景hex> <基底hex> [层:hex:alpha ...]");
  console.error("  层从远到近依次叠放，格式 hex:alpha，如 '#ffffff:0.6'");
  process.exit(1);
}
let bg = toRgb(base);
for (const l of layers) {
  const [hex, a] = l.split(":");
  bg = over(toRgb(hex), Number(a), bg);
}
const c = contrast(toRgb(fg), bg);
console.log(
  `合成背景 rgb(${bg.map((v) => Math.round(v * 255)).join(", ")}) 亮度 ${lum(bg).toFixed(3)}`,
);
console.log(
  `对比度 ${c.toFixed(2)}:1  → ${c >= 7 ? "AAA" : c >= 4.5 ? "AA(正文)" : c >= 3 ? "AA(大字)" : "不达标"}`,
);
