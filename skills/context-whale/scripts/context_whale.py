#!/usr/bin/env python3
"""context-whale v0.0.4

User-level skill entry point. It normalizes a harness session, estimates the
context composition, writes a JSON report and renders the whale-girl bento UI.

Explicit invocation is enforced here: `run` and `render` require --explicit.
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import adapters  # noqa: E402
from analyze import finalize  # noqa: E402
import render as renderer  # noqa: E402

TOOL_VERSION = "0.0.4"
VERSION_FILE = os.path.join(SKILL_DIR, "VERSION")


def out_json(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def fail(code, message, extra=None):
    payload = {"ok": False, "error": {"code": code, "message": message}}
    if extra:
        payload.update(extra)
    out_json(payload, 1)


def require_explicit(args):
    if not getattr(args, "explicit", False):
        fail("explicit_invocation_required",
             "context-whale 只能由用户显式调用。请使用 /context-whale，或在命令中加 --explicit。")


def read_version():
    try:
        return open(VERSION_FILE, encoding="utf-8").read().strip() or TOOL_VERSION
    except Exception:
        return TOOL_VERSION


def validate_report(report):
    """Fail before rendering when the normalized numbers are impossible."""
    used = (report.get("window") or {}).get("used")
    cache = (report.get("usage") or {}).get("cache_hit_pct")
    sid = (report.get("session") or {}).get("id")
    if not sid:
        return "session id missing"
    if used is None or used <= 0:
        return "used tokens must be positive"
    if cache is not None and not (0 <= cache <= 100):
        return "cache hit pct out of range: %.2f" % cache
    known = [c for c in report.get("categories") or []
             if c.get("recorded") and c.get("share") is not None]
    if not known:
        return "no recorded categories"
    total = sum(c["share"] for c in known)
    if abs(total - 1.0) > 0.01:
        return "recorded shares do not sum to 1 (%.4f)" % total
    return None


def cmd_list(args):
    cwd = args.cwd or os.getcwd()
    items = adapters.discover_all(cwd)
    payload = {
        "ok": True,
        "tool_version": read_version(),
        "cwd": cwd,
        "sessions": items,
    }
    if args.json:
        out_json(payload)
    if not items:
        print("没有找到可分析的会话。")
        return
    print("HARNESS      FIDELITY  SESSION                                    UPDATED")
    for it in items[:30]:
        ts = it.get("updated")
        when = time.strftime("%m-%d %H:%M", time.localtime(ts / 1000.0)) if ts else "—"
        print("%-12s %-8s %-42s %s" % (it.get("harness"), it.get("fidelity"),
                                       str(it.get("session"))[:42], when))
    print("\n用 --session <id> / --harness <name> 指定；默认按 cwd 选最合适的一个。")


def cmd_analyze(args):
    cwd = args.cwd or os.getcwd()
    report = adapters.analyze_session(harness=args.harness, session=args.session,
                                      cwd=cwd)
    if not report:
        fail("session_not_found",
             "没有找到可分析的会话。先运行 list 看看有哪些。",
             {"cwd": cwd, "sessions": adapters.discover_all(cwd)[:20]})
    report = finalize(report)
    report["tool_version"] = read_version()
    if args.json_only:
        out_json({"ok": True, "tool_version": report["tool_version"], "report": report})
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_run(args):
    require_explicit(args)
    if not args.out:
        fail("missing_out", "run 需要 --out <会话可视化目录>，用于写入 HTML/JSON 和素材。")
    cwd = args.cwd or os.getcwd()
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out_dir, exist_ok=True)

    report = adapters.analyze_session(harness=args.harness, session=args.session, cwd=cwd)
    if not report:
        fail("session_not_found",
             "没有找到可分析的会话。先运行 list 看看有哪些。",
             {"cwd": cwd, "sessions": adapters.discover_all(cwd)[:20]})
    target = args.session
    if target and not ("/" in target or target.endswith((".jsonl", ".zstd"))):
        if (report.get("session") or {}).get("id") != target:
            fail("session_mismatch",
                 "解析到的会话与请求的 session 不一致。",
                 {"requested": target, "resolved": (report.get("session") or {}).get("id")})
    report = finalize(report)
    report["tool_version"] = read_version()
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    problem = validate_report(report)
    if problem:
        fail("report_invalid", problem,
             {"harness": report.get("harness"), "session": (report.get("session") or {}).get("id")})

    json_path = os.path.join(out_dir, "context-report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    html_path = None
    if not args.json_only:
        try:
            html_path = renderer.render(report, out_dir, SKILL_DIR)
        except RuntimeError as e:
            fail("assets_missing", str(e),
                 {"hint": "运行 context_whale.py bootstrap-assets 或在 skill 的 assets/ 下补齐素材。"})

    # append a compact history line
    try:
        hist_dir = os.path.join(SKILL_DIR, "data")
        os.makedirs(hist_dir, exist_ok=True)
        groups = {g["key"]: g for g in report.get("groups") or []}
        row = {
            "ts": int(time.time() * 1000),
            "tool_version": report["tool_version"],
            "harness": report.get("harness"),
            "fidelity": report.get("fidelity"),
            "session": (report.get("session") or {}).get("id"),
            "model": (report.get("session") or {}).get("model"),
            "used_tokens": (report.get("window") or {}).get("used"),
            "window_limit": (report.get("window") or {}).get("limit"),
            "window_pct": (report.get("window") or {}).get("pct"),
            "groups": {k: {"tokens": v.get("tokens"), "share": v.get("share")}
                       for k, v in groups.items()},
        }
        with open(os.path.join(hist_dir, "history.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass

    top = sorted([c for c in (report.get("categories") or [])
                  if c.get("recorded") and c.get("share") is not None],
                 key=lambda x: x["share"], reverse=True)[:3]
    summary = {
        "headline": report.get("headline"),
        "used_tokens": (report.get("window") or {}).get("used"),
        "window_limit": (report.get("window") or {}).get("limit"),
        "window_pct": (report.get("window") or {}).get("pct"),
        "top": [{"key": c["key"], "label": c["label"],
                 "share": round(c["share"] * 100, 2) if c.get("share") is not None else None} for c in top],
        "insights": [i.get("title") for i in (report.get("insights") or [])],
    }
    out_json({
        "ok": True,
        "tool_version": report["tool_version"],
        "harness": report.get("harness"),
        "fidelity": report.get("fidelity"),
        "session": (report.get("session") or {}).get("id"),
        "html_path": html_path,
        "json_path": json_path,
        "summary": summary,
    })


def cmd_bootstrap(args):
    require_explicit(args)
    script = os.path.join(HERE, "bootstrap_assets.py")
    if not os.path.exists(script):
        fail("bootstrap_missing", "bootstrap_assets.py 不存在。")
    os.execv(sys.executable, [sys.executable, script] + (["--run"] if args.run else []))


def main():
    parser = argparse.ArgumentParser(prog="context-whale", description="Harness context window usage report")
    parser.add_argument("--cwd", default=None, help="target working directory")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list analyzable sessions")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_analyze = sub.add_parser("analyze", help="analyze and print the JSON report")
    p_analyze.add_argument("--harness", default="auto")
    p_analyze.add_argument("--session", default=None)
    p_analyze.add_argument("--json-only", action="store_true")
    p_analyze.set_defaults(func=cmd_analyze)

    p_run = sub.add_parser("run", help="analyze + render HTML/JSON")
    p_run.add_argument("--explicit", action="store_true")
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--harness", default="auto")
    p_run.add_argument("--session", default=None)
    p_run.add_argument("--json-only", action="store_true")
    p_run.add_argument("--refresh-assets", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_boot = sub.add_parser("bootstrap-assets", help="check / generate whale-girl assets with iart")
    p_boot.add_argument("--explicit", action="store_true")
    p_boot.add_argument("--run", action="store_true", help="actually submit iart generations")
    p_boot.set_defaults(func=cmd_bootstrap)

    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
