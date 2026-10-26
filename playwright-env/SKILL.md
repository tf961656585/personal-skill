---
name: playwright-env
description: |
  本机 Playwright 环境口径：npm 全局链路、浏览器池位置与保护、升级与重置命令、已知僵尸依赖。
  触发场景包括但不限于：
  - 浏览器自动化、网页截图、抓取等任务使用 playwright / playwright-cli 时
  - 安装、升级、重置或排障 playwright / playwright-cli / 浏览器内核时
  - 磁盘清理、缓存清理、清理 ~/Library 等动作可能触及浏览器目录时（防止误删浏览器池）
  - 排查「浏览器未安装 / Executable doesn't exist」类报错时
  边界：playwright-cli 的命令用法见 playwright-cli skill（该目录由安装器刷新覆盖，自定义口径一律写在本 skill）。
---

# 本机 Playwright 环境口径（playwright-env）

本机浏览器自动化统一用 npm 全局的 `playwright` 与 `playwright-cli`（/opt/homebrew 前缀，非 brew formula）；不为一次性脚本新装 playwright 副本，项目内按版本 pin 依赖属正常；全家族（npm 全局、CLI 内嵌核、项目副本、Python 版）共享同一浏览器池。

## 浏览器池（最高优先级保护项）

- 唯一位置：`~/Library/Playwright`，由 `~/.zshenv` 的 `PLAYWRIGHT_BROWSERS_PATH` 指向。禁止把它当缓存清理；`~/Library/Caches/ms-playwright` 出现内容即环境变量失联信号，先恢复变量再排查，不要直接重装浏览器。
- 理由：浏览器池曾在默认缓存目录被清理工具清掉，迁出动因即此；全家族共享同一池，清掉即同时断粮（2026-09-25 迁出）。

## 升级一条链（官方无单条更新命令）

```bash
npm i -g playwright@latest @playwright/cli@latest && playwright install && playwright-cli install-browser && playwright-cli install --skills=agents --global
```

- 最后一段刷新用户级 skill；skillCheck 只检查 cwd 下的副本，过期不会自动提示，升级后必须手动跑。

## 旧代浏览器无自动 GC

CLI 内嵌核随版本演进可能领先正式版、多出一代构建。重置杠杆：

```bash
playwright uninstall --all && playwright install && playwright-cli install-browser
```

## 已知僵尸依赖

workbuddy 自带 Python 环境里的 playwright 1.62 所需浏览器已不在池中，勿当在役依赖排障（2026-09-25 核实，用户裁决留档不动）。

## 目录边界

- `~/.agents/skills/playwright-cli/` 整目录由 `playwright-cli install --skills` 刷新覆盖，本口径及任何自定义内容不得写入该目录——本 skill 独立成目录正是为此。
- ZCode 的 browser-use 插件不走 playwright，属独立链路，不受浏览器池影响。
