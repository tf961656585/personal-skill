#!/usr/bin/env node
// 原型结构巡检（不进硬门禁）：执行 prototype-standard skill 的结构契约（跨项目通用 master）。
// 检查项：内联 <style>/<script> 体、inline 事件属性、行数预算（500/600/800）、
// 原型间互相引用、<script src>/<link> 断链、加载顺序（data.js 先于 app.js、app.js 最后）、
// 非令牌 CSS 硬编码 hex（warning 级）。
// 用法：node prototype-audit.mjs [项目根] [--tokens <令牌文件名>]
//   项目根默认 cwd；令牌文件未指定时自动探测（tokens.css / node-prototype.css）。
// error 级未清零时退出码 1；warning 级只报告不阻断。手动或巡检时运行，不作为交付放行门禁。
// 项目内副本是该项目的事实源；本 master 更新后可选同步（同步义务记项目投影 prototypes/README.md）。
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const rootArgIdx = args.findIndex((a) => !a.startsWith("--"));
const ROOT = path.resolve(
  rootArgIdx === -1 ? "." : args[rootArgIdx],
);
const tokensFlagIdx = args.indexOf("--tokens");
const TOKENS_FLAG = tokensFlagIdx !== -1 ? args[tokensFlagIdx + 1] : undefined;

const PROTO_DIR = path.join(ROOT, "prototypes");
const SHARED = "shared";
const TOKEN_CANDIDATES = [TOKENS_FLAG, "tokens.css", "node-prototype.css"].filter(Boolean);

const BUDGET = {
  indexHtml: 500,
  pageFile: 600,
  sharedFile: 800,
};

const errors = [];
const warnings = [];

const fail = (msg) => errors.push(msg);
const warn = (msg) => warnings.push(msg);

function readText(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    return null;
  }
}

function countLines(text) {
  if (text.length === 0) return 0;
  const count = text.split("\n").length;
  return text.endsWith("\n") ? count - 1 : count;
}

if (!fs.existsSync(PROTO_DIR)) {
  console.error(`[prototype:audit] prototypes/ 目录不存在：${PROTO_DIR}`);
  process.exit(1);
}

const entries = fs.readdirSync(PROTO_DIR, { withFileTypes: true })
  .filter((d) => d.isDirectory() && d.name !== SHARED && !d.name.startsWith("."))
  .map((d) => d.name)
  .sort();

for (const proto of entries) {
  const dir = path.join(PROTO_DIR, proto);
  const indexFile = path.join(dir, "index.html");
  const html = readText(indexFile);
  if (html === null) {
    fail(`${proto}: 缺少 index.html`);
    continue;
  }

  // 1) 禁止内联 <style> / <script> 体（只允许空标签或带 src/href 的引用标签）
  const styleBody = /<style[^>]*>\s*\S[\s\S]*?<\/style>/.exec(html);
  if (styleBody) fail(`${proto}/index.html: 存在内联 <style> 体（样式拆到 style.css）`);
  const scriptBodyRe = /<script(?![^>]*\bsrc=)[^>]*>\s*\S[\s\S]*?<\/script>/.exec(html);
  if (scriptBodyRe) fail(`${proto}/index.html: 存在内联 <script> 体（行为拆到 data.js / 域文件 / app.js）`);

  // 2) 禁止 inline 事件属性
  const inlineHandler = /\son(click|change|input|keydown|keyup|submit|load|error|mouseover|mouseout|focus|blur)\s*=/i.exec(html);
  if (inlineHandler) fail(`${proto}/index.html: 存在 inline 事件属性 ${inlineHandler[0].trim()}（接线集中 app.js）`);

  // 3) 引用的本地文件必须存在；原型文件不得引用兄弟原型目录（共享只走 ../shared/）
  const refRe = /(?:<script[^>]*\bsrc|<link[^>]*\bhref)\s*=\s*["']([^"']+)["']/g;
  for (const match of html.matchAll(refRe)) {
    const ref = match[1];
    if (/^(https?:|data:|#|mailto:)/i.test(ref)) continue;
    const resolved = path.normalize(path.join(dir, ref));
    const relToProto = path.relative(PROTO_DIR, resolved);
    if (relToProto.startsWith("..")) {
      fail(`${proto}/index.html: 引用越出 prototypes/ 目录：${ref}`);
      continue;
    }
    const firstSegment = relToProto.split(path.sep)[0];
    if (firstSegment !== SHARED && firstSegment !== proto) {
      fail(`${proto}/index.html: 引用了兄弟原型目录 ${ref}（跨原型共享一律下沉 prototypes/shared/）`);
    }
    if (!fs.existsSync(resolved)) fail(`${proto}/index.html: 断链 ${ref}`);
  }

  // 4) 加载顺序契约：页面脚本里 data.js 必须先于 app.js；app.js 必须是最后一个页面脚本
  const pageScripts = [...html.matchAll(/<script[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/g)]
    .map((m) => m[1])
    .filter((ref) => !ref.includes(`/${SHARED}/`) && !ref.startsWith(`${SHARED}/`));
  const dataIndex = pageScripts.indexOf("data.js");
  const appIndex = pageScripts.indexOf("app.js");
  if (dataIndex !== -1 && appIndex !== -1 && dataIndex > appIndex) {
    fail(`${proto}/index.html: data.js 必须在 app.js 之前加载`);
  }
  if (appIndex !== -1 && appIndex !== pageScripts.length - 1) {
    fail(`${proto}/index.html: app.js 必须是最后一个页面脚本（当前其后还有 ${pageScripts.slice(appIndex + 1).join(", ")}）`);
  }

  // 5) 行数预算
  const indexLines = countLines(html);
  if (indexLines > BUDGET.indexHtml) {
    fail(`${proto}/index.html: ${indexLines} 行超出预算 ${BUDGET.indexHtml}（把样式/数据/行为拆出去）`);
  }
  for (const file of fs.readdirSync(dir)) {
    if (!/\.(js|css)$/.test(file)) continue;
    const lines = countLines(readText(path.join(dir, file)) ?? "");
    if (lines > BUDGET.pageFile) {
      fail(`${proto}/${file}: ${lines} 行超出页面文件预算 ${BUDGET.pageFile}（按职责域再拆）`);
    }
  }
}

// 6) shared 件预算与 CSS 令牌纪律
const sharedDir = path.join(PROTO_DIR, SHARED);
if (fs.existsSync(sharedDir)) {
  for (const file of fs.readdirSync(sharedDir)) {
    if (!/\.(js|css)$/.test(file)) continue;
    const lines = countLines(readText(path.join(sharedDir, file)) ?? "");
    if (lines > BUDGET.sharedFile) {
      fail(`${SHARED}/${file}: ${lines} 行超出 shared 预算 ${BUDGET.sharedFile}（按域拆多件）`);
    }
  }
  // 令牌文件解析：--tokens 显式指定时严格生效（拼写错误立即暴露）；未指定时候选名探测；都无则跳过 hex 检查
  const tokenFile = TOKENS_FLAG !== undefined
    ? (fs.existsSync(path.join(sharedDir, TOKENS_FLAG)) ? TOKENS_FLAG : undefined)
    : TOKEN_CANDIDATES.find((f) => fs.existsSync(path.join(sharedDir, f)));
  if (!tokenFile) {
    console.warn(`[prototype:audit] WARN 未找到令牌文件（候选：${TOKEN_CANDIDATES.join(", ")}），跳过硬编码 hex 检查——用 --tokens <文件名> 指定`);
  } else {
    for (const root of [sharedDir, ...entries.map((p) => path.join(PROTO_DIR, p))]) {
      for (const file of fs.readdirSync(root).filter((f) => f.endsWith(".css"))) {
        if (root === sharedDir && file === tokenFile) continue;
        const text = readText(path.join(root, file));
        if (!text) continue;
        const hexCount = (text.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).length;
        if (hexCount > 0) {
          warn(`${path.relative(PROTO_DIR, path.join(root, file))}: 含 ${hexCount} 处硬编码 hex（颜色应经 ${tokenFile} 令牌消费）`);
        }
      }
    }
  }
}

// 7) 页面 JS 互相引用兄弟原型目录（文件内容层面）
for (const proto of entries) {
  const dir = path.join(PROTO_DIR, proto);
  for (const file of fs.readdirSync(dir).filter((f) => /\.(js|css)$/.test(f))) {
    const text = readText(path.join(dir, file));
    if (!text) continue;
    for (const match of text.matchAll(/["'`](?:\.\.\/|\.\.\\)([A-Za-z0-9._-]+)["'`/]/g)) {
      const target = match[1];
      if (target !== SHARED && entries.includes(target)) {
        fail(`${proto}/${file}: 引用了兄弟原型 ../${target}（跨原型共享一律下沉 prototypes/shared/）`);
      }
    }
  }
}

const checked = entries.length;
console.log(`[prototype:audit] checked ${checked} prototypes (${PROTO_DIR})`);
for (const message of warnings) console.warn(`[prototype:audit] WARN ${message}`);
for (const message of errors) console.error(`[prototype:audit] ERROR ${message}`);
if (errors.length > 0) {
  console.error(`[prototype:audit] ${errors.length} error(s), ${warnings.length} warning(s) —— 按 prototype-standard skill 结构契约与项目投影 prototypes/README.md 修复`);
  process.exit(1);
}
console.log(`[prototype:audit] OK${warnings.length ? `（${warnings.length} 个 warning 级提示）` : ""}`);
