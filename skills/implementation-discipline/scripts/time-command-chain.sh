#!/bin/bash
# time-command-chain.sh — 命令链分段计时工具
#
# 排查"整条链慢但不知道慢在哪一段"时，先量测再动手。每段命令的 START/END
# 时间戳（unix 秒）与退出码写入日志文件，parse 模式解析出每段耗时并按耗时降序汇总。
#
# 用法 A（链模式，一次性计时整条链）：
#   time-command-chain.sh run <logfile> <命令...> ::: <命令...> ::: <命令...>
#   time-command-chain.sh parse <logfile>
#   例：
#   time-command-chain.sh run /tmp/chain.log pnpm build:typecheck-deps ::: pnpm typecheck:workspaces ::: pnpm lint
#   time-command-chain.sh parse /tmp/chain.log
#   分隔符是独立 token ":::"（不用 "--"，避让 `pnpm run x -- --flag` 这类命令自带的独立 --）。
#
# 用法 B（库模式，适合复杂脚本内嵌）：
#   source /path/to/time-command-chain.sh
#   CHAIN_TIMING_LOG=/tmp/chain.log   # 可选，默认 /tmp/chain-timing.log
#   : > "$CHAIN_TIMING_LOG"           # 库模式不自动清空，调用方决定是否截断
#   step "build" pnpm run build
#   step "test" pnpm run test:scripts
#
# 日志行格式：
#   === STEP START <名称> <unix秒>
#   === STEP END <名称> rc=<退出码> <unix秒>
# parse 按出现顺序配对同名的相邻 START/END，支持同名多段（顺序配对）。

# 库模式：执行一段命令并计时。用法：step <名称> <命令...>
step() {
  local name="$1"; shift
  local log="${CHAIN_TIMING_LOG:-/tmp/chain-timing.log}"
  echo "=== STEP START $name $(date +%s)" >> "$log"
  "$@" >> "$log" 2>&1
  local rc=$?
  echo "=== STEP END $name rc=$rc $(date +%s)" >> "$log"
  return $rc
}

# 链模式：按独立 token ":::" 切分参数为若干段，每段按原始参数直接执行（不经 shell 重解析，保引号语义）
run_chain() {
  local log="$1"; shift
  # 容错：允许首段前多写一个 "--"（与常见习惯一致），但不作分隔符
  if [ "${1:-}" = "--" ]; then shift; fi
  : > "$log"

  # 记录每段起始下标（1-based，相对当前 "$@"），并追加哨兵统一算段长
  local -a starts=(1)
  local n=0
  local arg
  for arg in "$@"; do
    if [ "$arg" = ":::" ]; then
      starts+=($((n + 2)))
    fi
    n=$((n + 1))
  done
  starts+=($((n + 2)))

  local chain_rc=0
  local gi start next glen name
  for gi in "${!starts[@]}"; do
    start="${starts[$gi]}"
    next="${starts[$((gi + 1))]:-0}"
    glen=$((next - start - 1))
    [ "$glen" -le 0 ] && continue
    name=$(printf '%s ' "${@:start:glen}")
    name="${name% }"
    CHAIN_TIMING_LOG="$log" step "$name" "${@:start:glen}" || chain_rc=1
  done
  return $chain_rc
}

# 解析模式：输出每段耗时（按耗时降序）与总计
parse_log() {
  python3 - "$1" <<'PYEOF'
import re, sys

path = sys.argv[1]
try:
    f = open(path)
except OSError:
    print(f'(日志文件不存在: {path})')
    sys.exit(1)
steps = []
cur = None
for line in f:
    m = re.match(r'=== STEP START (.+?) (\d+)\s*$', line)
    if m:
        cur = (m.group(1), int(m.group(2)))
        continue
    m = re.match(r'=== STEP END (.+?) rc=(\d+) (\d+)\s*$', line)
    if m and cur and cur[0] == m.group(1):
        steps.append((m.group(1), m.group(2) == '0', int(m.group(3)) - cur[1]))
        cur = None

if not steps:
    print(f'(日志无完整 START/END 配对: {path})')
    sys.exit(1)

fails = [n for n, ok, d in steps if not ok]
for name, ok, dur in sorted(steps, key=lambda x: -x[2]):
    mark = 'FAIL' if not ok else 'ok'
    print(f'{dur:6d}s  {mark:4s}  {name}')
print(f'{sum(d for _, _, d in steps):6d}s  TOTAL ({len(steps)} 段)')
if fails:
    print(f'FAIL: {", ".join(fails)}')
    sys.exit(1)
PYEOF
}

main() {
  if [ $# -lt 2 ]; then
    sed -n '2,26p' "${BASH_SOURCE[0]}"
    exit 1
  fi
  case "$1" in
    run)   shift; local log="$1"; shift; run_chain "$log" "$@" ;;
    parse) parse_log "$2" ;;
    *)     sed -n '2,26p' "${BASH_SOURCE[0]}"; exit 1 ;;
  esac
}

# 直接执行时进入 main；被 source 时只注入 step()
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
