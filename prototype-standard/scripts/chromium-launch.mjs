// playwright chromium 启动回退：revision 失配时改用缓存中已装的浏览器。
//
// 背景：`chromium.launch()` 无参会按 playwright 版本要求固定 revision（如
// chromium_headless_shell-1243）。本机 ms-playwright 缓存只有旧 revision 时，启动硬失败并
// 提示 `npx playwright install`——那需要联网下载。本模块在默认启动失败后，扫描缓存里实际
// 存在的 chromium，用 executablePath 重试；离线或已装旧版本时照样能跑。
//
// 路径易错点：playwright 在 mac 上的目录名是 chrome-mac-arm64 / chrome-mac-x64，可执行文件
// 名是 "Google Chrome for Testing"（不是 Chromium.app）——按直觉拼路径会找不到文件。
//
// 消费方：prototype-page-sweep.mjs 与 prototype-dom-smoke.template.mjs。后者会被复制到 /tmp，
// 因此以绝对路径 import 本模块（与本 skill 既有脚本使用全局 playwright 绝对路径同源）。
// 改本文件的启动语义时两处消费方同步受益，不需要各自维护一份。
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** ms-playwright 缓存根：尊重 PLAYWRIGHT_BROWSERS_PATH，否则按平台默认位置。 */
export function resolveBrowsersCacheDir() {
  if (process.env.PLAYWRIGHT_BROWSERS_PATH) return process.env.PLAYWRIGHT_BROWSERS_PATH;
  const home = os.homedir();
  if (process.platform === "darwin") return path.join(home, "Library", "Caches", "ms-playwright");
  if (process.platform === "win32") {
    return path.join(process.env.LOCALAPPDATA || path.join(home, "AppData", "Local"), "ms-playwright");
  }
  return path.join(home, ".cache", "ms-playwright");
}

/** 完整 chromium 的可执行文件相对路径（按平台择一命中）。 */
const CHROMIUM_RELATIVE_PATHS = [
  path.join("chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
  path.join("chrome-mac-x64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
  path.join("chrome-linux", "chrome"),
  path.join("chrome-win", "chrome.exe"),
];

/** headless shell 的可执行文件相对路径（仅装了它时的兜底）。 */
const HEADLESS_SHELL_RELATIVE_PATHS = [
  path.join("chrome-headless-shell-mac-arm64", "chrome-headless-shell"),
  path.join("chrome-headless-shell-mac-x64", "chrome-headless-shell"),
  path.join("chrome-headless-shell-linux64", "chrome-headless-shell"),
  path.join("chrome-headless-shell-win64", "chrome-headless-shell.exe"),
];

/**
 * 取缓存中已装的 chromium 可执行文件路径；没有则返回 null。
 *
 * 同一前缀下可能有多个 revision，取编号最大的（最新）；完整 chromium 优先于 headless shell。
 * 注意 "chromium-" 与 "chromium_headless_shell-" 是不同前缀，不会互相误匹配。
 */
export function resolveCachedChromium() {
  const cache = resolveBrowsersCacheDir();
  if (!fs.existsSync(cache)) return null;
  const entries = fs.readdirSync(cache);

  const pickByPrefix = (prefix, relativePaths) => {
    const revisions = entries
      .filter((name) => name.startsWith(prefix))
      .map((name) => ({ name, revision: Number(name.slice(prefix.length)) || 0 }))
      .sort((a, b) => b.revision - a.revision);
    for (const { name } of revisions) {
      for (const relative of relativePaths) {
        const candidate = path.join(cache, name, relative);
        if (fs.existsSync(candidate)) return candidate;
      }
    }
    return null;
  };

  return (
    pickByPrefix("chromium-", CHROMIUM_RELATIVE_PATHS) ||
    pickByPrefix("chromium_headless_shell-", HEADLESS_SHELL_RELATIVE_PATHS)
  );
}

/**
 * 启动 chromium：先用 playwright 自己的 revision，失败再回退到缓存中已装的版本。
 *
 * 回退发生时打印一行说明——静默换浏览器会让"为什么这次跑得起来"无从追溯。
 * 两条路径都失败时抛原始错误，保留 playwright 自己的诊断信息（含它期望的 revision）。
 */
export async function launchChromium(chromium, options = {}) {
  try {
    return await chromium.launch(options);
  } catch (error) {
    const cached = resolveCachedChromium();
    if (!cached) throw error;
    console.log(`… chromium 启动失败（通常是 revision 失配），回退到缓存版本：${cached}`);
    return await chromium.launch({ ...options, executablePath: cached });
  }
}
