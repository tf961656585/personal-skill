#!/usr/bin/env node
// 原型全页运行时报错扫描（不进硬门禁）：加载 prototypes/ 下每个 */index.html，
// 收集 pageerror 与 console.error——共享脚本（prototypes/shared/*）改动后的破坏面巡检。
// 用法：node prototype-page-sweep.mjs [--base <http 基址>]
//   --base 缺省时用 file:// 直开（Playwright 库支持；playwright-cli 的 file:// 限制不适用本路径）。
// 任一页面出现报错退出码 1。手动运行，不作为交付放行门禁。
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { launchChromium } from "./chromium-launch.mjs";

const baseIdx = process.argv.indexOf("--base");
const BASE = baseIdx !== -1 ? process.argv[baseIdx + 1] : null;
const ROOT = path.resolve(".");
const PROTO = path.join(ROOT, "prototypes");

async function importPlaywright() {
  try { return await import("playwright"); } catch { /* 仓库本地未装时落到全局 */ }
  for (const p of [
    "/opt/homebrew/lib/node_modules/@playwright/cli/node_modules/playwright/index.mjs",
    "/usr/local/lib/node_modules/@playwright/cli/node_modules/playwright/index.mjs",
  ]) {
    try { return await import(pathToFileURL(p).href); } catch { /* 试下一个 */ }
  }
  console.error("✗ 找不到 playwright：本地依赖或全局 @playwright/cli 均不可用");
  process.exit(1);
}

const pages = fs.existsSync(PROTO)
  ? fs.readdirSync(PROTO, { withFileTypes: true })
      .filter((d) => d.isDirectory() && fs.existsSync(path.join(PROTO, d.name, "index.html")))
      .map((d) => d.name)
  : [];
if (!pages.length) { console.error("✗ 未找到任何 prototypes/*/index.html"); process.exit(1); }

const { chromium } = await importPlaywright();
const browser = await launchChromium(chromium);
let bad = 0;
for (const name of pages) {
  const page = await browser.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errs.push(`console: ${m.text()}`); });
  const url = BASE ? `${BASE.replace(/\/$/, "")}/${name}/index.html` : pathToFileURL(path.join(PROTO, name, "index.html")).href;
  try {
    await page.goto(url, { waitUntil: "load" });
    await page.waitForTimeout(600);   // classic script 异步初始化留窗
  } catch (e) {
    errs.push(`goto 失败: ${e.message.split("\n")[0]}`);
  }
  console.log(`${errs.length ? "✗" : "✓"} ${name}${errs.length ? " — " + errs.join(" | ") : ""}`);
  if (errs.length) bad++;
  await page.close();
}
await browser.close();
process.exit(bad ? 1 : 0);
