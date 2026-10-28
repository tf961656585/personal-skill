// 原型 DOM 交互冒烟模板：复制到 /tmp 按目标原型填断言，不进仓库、不进门禁。
// 纪律：只断言 DOM 文本/属性/计算值（主线程无视觉，禁截图）；断言失败退出码 1。
// 用法：node <副本>.mjs （先起静态服务：pnpm prototype:preview 或 python3 -m http.server <port> --directory prototypes）
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "/opt/homebrew/lib/node_modules/@playwright/cli/node_modules/playwright/index.mjs";
// ↑ 本机全局安装路径；不可用时按 prototype-page-sweep.mjs 的 importPlaywright 降级链处理

// chromium 启动回退：playwright 版本要求的 revision 未装时，改用 ms-playwright 缓存中已装的版本，
// 免去 `npx playwright install` 的联网下载（细节见 chromium-launch.mjs 头注释）。
// 本文件会被复制到 /tmp，故按候选路径动态 import；都找不到时退回普通启动，不影响断言逻辑。
async function importLaunchChromium() {
  const candidates = [
    // 在本 skill 目录内原样运行时（fileURLToPath 而非 .pathname —— 后者会把空格等转义成 %20）
    fileURLToPath(new URL("./chromium-launch.mjs", import.meta.url)),
    path.join(os.homedir(), ".agents", "skills", "prototype-standard", "scripts", "chromium-launch.mjs"),
  ];
  for (const file of candidates) {
    if (!fs.existsSync(file)) continue;
    try { return (await import(pathToFileURL(file).href)).launchChromium; } catch { /* 试下一个 */ }
  }
  return null;
}

const launchChromium = (await importLaunchChromium()) ?? ((c) => c.launch());
const browser = await launchChromium(chromium);
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const fails = [];
const ok = (cond, msg) => { console.log((cond ? "  ✓ " : "  ✗ ") + msg); if (!cond) fails.push(msg); };

await page.goto("http://127.0.0.1:4173/<原型>/index.html");
await page.waitForTimeout(400);

// 经典脚本的全局函数可直接 evaluate 调用（如 selectModelById("...")）
// await page.evaluate(() => selectModelById("...")); await page.waitForTimeout(200);

// 断言示例（按需替换）：
// const texts = await page.locator("<selector>").allTextContents();
// ok(texts.every(t => !t.includes("级")), "无硬凑类比文案");
// ok(await page.locator("[aria-disabled='true']").count() === 1, "禁用态前置");
// const title = await page.locator("<selector>").getAttribute("title");   // 禁用档 why
// await page.locator("<disabled selector>").dispatchEvent("click");       // aria-disabled 件 click 会被拒，用 dispatchEvent
// const head = await page.locator("<header selector>").textContent();     // 联动后读派生文案
//
// —— 文案层断言：界面不得出现内部术语 / 生造词（静态巡检 prototype:audit 与页面扫错都不覆盖这一类）
//    判据：控件标签用一个短名词、值用动作词；词表随项目维护，以被验收原型所属仓库的界面文案规范为准。
//    注意 body.textContent 会把隐藏面板（决策抽屉等）也算进去——只验收产品界面时改取具体容器。
// const bodyText = await page.locator("body").textContent();
// const FORBIDDEN = ["底座", "锚点", "投影", "准入", "执行确认", "自动连发"];
// const hit = FORBIDDEN.filter((w) => bodyText.includes(w));
// ok(hit.length === 0, "界面无禁用词" + (hit.length ? "（命中：" + hit.join("、") + "）" : ""));

console.log(fails.length ? `✗ ${fails.length} 项失败` : "✓ 全部通过");
await browser.close();
process.exit(fails.length ? 1 : 0);
