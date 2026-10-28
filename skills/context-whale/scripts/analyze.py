#!/usr/bin/env python3
"""Normalization, token estimation, grouping and deterministic insights."""

import re

from adapters import CATEGORIES, CATEGORY_LABELS

GROUPS = [
    {"key": "tool_results", "label": "工具结果", "icon": "icon-tools.png", "color": "tools",
     "keys": ["tool_results"]},
    {"key": "assistant_reasoning", "label": "助手思考", "icon": "icon-reason.png", "color": "reason",
     "keys": ["assistant_reasoning"]},
    {"key": "tool_definitions", "label": "工具定义", "icon": "icon-defs.png", "color": "defs",
     "keys": ["tool_definitions"]},
    {"key": "rest", "label": "调用与注入", "icon": "icon-skills.png", "color": "rest",
     "keys": ["tool_calls", "injection_skills", "system_prompt", "injection_agents",
              "injection_other", "injection_date", "other_blocks", "assistant_text"]},
    {"key": "user_input", "label": "你的话", "icon": "icon-pearl.png", "color": "user",
     "keys": ["user_input"]},
]

TOTAL_KEY = "known_total"


def estimate_tokens(text):
    if not text:
        return 0.0
    text = str(text)
    cjk = len(re.findall(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    return cjk + (len(text) - cjk) / 3.6


def _fmt_int(n):
    if n is None:
        return "—"
    return "{:,}".format(int(round(n)))


def _pct(x, digits=1):
    if x is None:
        return "—"
    return ("%." + str(digits) + "f%%") % x


def _is_missing(report, key):
    cov = report.get("coverage") or {}
    if key == "tool_definitions":
        return cov.get("tool_definitions") is False
    if key == "system_prompt":
        return cov.get("system_prompt") is False
    if key in ("injection_skills", "injection_agents", "injection_date"):
        return cov.get("system_prompt") is False
    return False


def finalize(report):
    events = report.pop("events", [])
    tool_counts = report.pop("_tool_counts", {}) or {}

    raw = {}
    counts = {}
    largest_results = []
    for key, text, meta in events:
        t = text or ""
        raw[key] = raw.get(key, 0.0) + estimate_tokens(t)
        counts[key] = counts.get(key, 0) + int((meta or {}).get("count") or 1)
        if key == "tool_results":
            largest_results.append({
                "tool_name": (meta or {}).get("tool_name") or "tool",
                "chars": len(t),
                "tokens_est": estimate_tokens(t),
            })

    total_raw = sum(raw.values())
    used = report.get("usage", {}).get("input_tokens")
    usage_source = report.get("usage", {}).get("usage_source", "estimated")
    if not used:
        used = int(round(total_raw)) if total_raw else None
        report["usage"]["input_tokens"] = used
    scale = (used / total_raw) if (used and total_raw) else 1.0

    cats = []
    known_total = 0
    for key, label in CATEGORIES:
        missing = _is_missing(report, key)
        recorded = not missing
        raw_val = raw.get(key, 0.0)
        if recorded:
            tokens = int(round(raw_val * scale))
            known_total += tokens
        else:
            tokens = None
        cats.append({
            "key": key,
            "label": label,
            "recorded": recorded,
            "tokens": tokens,
            "share": None,  # filled below
            "count": counts.get(key, 0),
            "top_item": None,
        })

    for c in cats:
        if c["recorded"] and known_total:
            c["share"] = c["tokens"] / known_total
        if c["key"] == "tool_results" and largest_results:
            top = max(largest_results, key=lambda x: x["chars"])
            c["top_item"] = {
                "tool_name": top["tool_name"],
                "chars": top["chars"],
                "tokens_est": int(round(top["tokens_est"] * scale)),
            }
        elif c["key"] == "tool_definitions" and c["recorded"]:
            c["top_item"] = {"count": c["count"]}
        elif c["key"] in ("user_input", "assistant_text") and c["recorded"]:
            c["top_item"] = {"count": c["count"]}

    report["categories"] = cats
    by_key = {c["key"]: c for c in cats}

    groups = []
    for g in GROUPS:
        keys = g["keys"]
        known = [by_key[k] for k in keys if by_key[k]["recorded"]]
        recorded = bool(known) or all(not _is_missing(report, k) for k in keys)
        tokens = sum(c["tokens"] or 0 for c in known) if recorded else None
        count = sum(c["count"] or 0 for c in known)
        share = (tokens / known_total) if (recorded and known_total and tokens is not None) else None
        groups.append({
            "key": g["key"], "label": g["label"], "icon": g["icon"], "color": g["color"],
            "recorded": recorded, "tokens": tokens, "share": share, "count": count,
            "parts": [{"key": c["key"], "share": c["share"], "tokens": c["tokens"]}
                      for c in known if c["share"]],
        })
    report["groups"] = groups

    # window
    w = report.get("window") or {}
    if used and w.get("limit"):
        w["used"] = used
        w["pct"] = used / w["limit"] * 100.0
    else:
        w["used"] = used
        w["pct"] = None
    report["window"] = w

    # series
    series = [x for x in (report.get("series") or []) if isinstance(x, int) and x > 0]
    if len(series) < 2 and used:
        series = [used]
    report["series"] = series

    # insights
    report["insights"] = build_insights(report)
    report["headline"] = build_headline(report)
    report["method"]["known_total_tokens"] = known_total
    report["method"]["usage_source"] = usage_source
    report["method"]["category_count"] = len([c for c in cats if c["recorded"]])
    return report


def build_headline(report):
    cats = [c for c in report["categories"] if c.get("recorded") and c.get("share") is not None]
    if not cats:
        return "这次没有读到可分析的上下文。"
    top = max(cats, key=lambda c: c["share"])
    label = {
        "tool_results": "工具结果", "assistant_reasoning": "助手思考",
        "tool_definitions": "工具定义", "tool_calls": "工具调用参数",
        "user_input": "你的话", "assistant_text": "助手回复",
        "injection_skills": "技能清单注入", "system_prompt": "系统提示",
    }.get(top["key"], top["label"])
    user = next((c for c in cats if c["key"] == "user_input"), None)
    if top["key"] == "tool_results":
        s = "工具结果占 %.1f%%" % (top["share"] * 100)
        if user and user.get("share") is not None:
            s += "，你的话只有 %.2f%%" % (user["share"] * 100)
        return s + "。"
    if top["key"] == "user_input":
        return "你的话占 %.2f%%，是这一轮最大的一格。" % (top["share"] * 100)
    return "%s占 %.1f%%，是这一轮最大的一格。" % (label, top["share"] * 100)


def build_insights(report):
    by_key = {c["key"]: c for c in report["categories"]}
    groups = {g["key"]: g for g in report["groups"]}
    known_total = report.get("method", {}).get("known_total_tokens") or 0
    insights = []

    def share(key):
        c = by_key.get(key)
        return c["share"] if c and c.get("share") is not None else 0.0

    tool = by_key.get("tool_results") or {}
    tool_share = share("tool_results")
    if tool_share >= 0.40:
        top = (tool.get("top_item") or {})
        top_chars = top.get("chars") or 0
        top_name = top.get("tool_name") or "tool"
        title = "工具结果吃掉 %.1f%%" % (tool_share * 100)
        if top_chars:
            title += "，最大单条 %s 输出 %s 字符" % (top_name, _fmt_int(top_chars))
        insights.append({
            "severity": "high", "icon": "icon-tools.png", "label": "最大的一格",
            "title": title + "。",
            "body": "整文件打印、整目录列举和全量日志，在长会话里会一遍遍回传；它们不是一次性的，而是每一轮都在。",
            "action": "命令加 | head -80 或 --json | jq 限字段；大文件用 Read 的 offset/limit 分段读。",
            "metric": tool_share,
        })

    defs = by_key.get("tool_definitions") or {}
    injection_share = sum(share(k) for k in
                          ("injection_skills", "injection_agents", "injection_other", "injection_date"))
    fixed = share("tool_definitions") + share("system_prompt") + injection_share
    if defs.get("recorded") and fixed >= 0.20:
        def_count = (defs.get("top_item") or {}).get("count") or defs.get("count") or 0
        insights.append({
            "severity": "medium", "icon": "icon-defs.png", "label": "固定开销",
            "title": "工具定义 + 注入占 %.1f%%，还没开始干活就先花了四分之一。" % (fixed * 100),
            "body": "工具 schema 和 harness 注入是每轮固定成本，不随任务变化。%s" %
                    ("当前有 %d 个工具定义全量下发。" % def_count if def_count else ""),
            "action": "精简不常用的 skill/插件描述，或为长任务换一个工具集更小的会话配置。",
            "metric": fixed,
        })

    user = by_key.get("user_input") or {}
    user_share = share("user_input")
    if user.get("recorded") and (user.get("tokens") or 0) == 0 and (user.get("count") or 0) == 0:
        insights.append({
            "severity": "high", "icon": "icon-pearl.png", "label": "窗口里没有你",
            "title": "本轮请求里已经看不到你的话了。",
            "body": "harness 发送的是滑动尾部窗口，较早的指令已经滑出；模型这一轮没有读到它。",
            "action": "长任务里定期复述目标与验收标准；开新会话时把当前锚点一起带过去。",
            "metric": 0.0,
        })
    elif user_share and user_share < 0.02:
        insights.append({
            "severity": "medium", "icon": "icon-pearl.png", "label": "你的话",
            "title": "真正由你输入的内容只有 %s tokens，占 %.2f%%。" %
                     (_fmt_int(user.get("tokens")), user_share * 100),
            "body": "长会话里，「任务锚点」很容易被工具结果和思考淹没。模型不是忘了，是注意力被摊薄了。",
            "action": "长会话开头用一句话写清「目标 / 不做什么 / 验收标准」；需要时让我复述锚点。",
            "metric": user_share,
        })

    if injection_share >= 0.25:
        insights.append({
            "severity": "medium", "icon": "icon-skills.png", "label": "注入",
            "title": "技能/环境注入占 %.1f%%（其中技能清单 %.1f%%）。" % (
                injection_share * 100, share("injection_skills") * 100),
            "body": "技能清单、子代理清单和运行时上下文会在每轮请求里重复；它们不是一次性的说明。",
            "action": "精简不常用的 skill 描述，或为长任务换一个技能集更小的会话配置。",
            "metric": injection_share,
        })

    calls_share = share("tool_calls")
    if calls_share >= 0.20:
        insights.append({
            "severity": "medium", "icon": "icon-skills.png", "label": "调用参数",
            "title": "工具调用参数占 %.1f%%，大段 JSON / patch 会每轮回传。" % (calls_share * 100),
            "body": "写文件、改文件和批量命令的参数本身也进入上下文；整文件重写比精确 edit 贵得多。",
            "action": "优先用精确 edit / 小范围 patch；批量操作拆成步骤，避免把整份文件塞进参数。",
            "metric": calls_share,
        })

    reasoning_share = share("assistant_reasoning")
    if reasoning_share >= 0.15:
        insights.append({
            "severity": "info", "icon": "icon-reason.png", "label": "思考也回传",
            "title": "助手思考占 %.1f%%，会随历史消息回传。" % (reasoning_share * 100),
            "body": "推理内容不是免费的旁白：在保留 reasoning 的会话里，它也会占用后续每一轮的上下文。",
            "action": "长会话里如果已经得出结论，及时 /compact；不要靠无限追加思考来维持上下文。",
            "metric": reasoning_share,
        })

    pct = report.get("window", {}).get("pct")
    if pct is not None and pct >= 60:
        insights.append({
            "severity": "high", "icon": "icon-defs.png", "label": "窗口水位",
            "title": "上下文窗口已用 %.1f%%。" % pct,
            "body": "继续堆积工具结果会逼近上限，触发压缩或截断。",
            "action": "先 /compact 或新开会话，把当前任务锚点带过去。",
            "metric": pct / 100.0,
        })

    cache = report.get("usage", {}).get("cache_hit_pct")
    if cache is not None and report.get("usage", {}).get("usage_source") == "per_call":
        if cache < 50:
            insights.append({
                "severity": "info", "icon": "icon-skills.png", "label": "缓存",
                "title": "缓存命中 %.0f%%，前缀变化较频繁。" % cache,
                "body": "缓存只影响费用和延迟，不减少上下文长度；但它能反映上下文是否在频繁重写。",
                "action": "连续做同类操作时，尽量保持工具输出格式稳定，减少前缀变化。",
                "metric": cache / 100.0,
            })
        elif cache >= 90:
            insights.append({
                "severity": "info", "icon": "icon-pearl.png", "label": "缓存稳定",
                "title": "缓存命中 %.1f%%，前缀基本没被重写。" % cache,
                "body": "命中缓存省的是费用和首字延迟，不缩短上下文；它说明这段会话的请求前缀很稳定。",
                "action": "保持当前节奏即可；真正需要盯的是上下文总量，而不是缓存率。",
                "metric": cache / 100.0,
            })

    if not defs.get("recorded") and report.get("fidelity") == "L2":
        insights.append({
            "severity": "info", "icon": "icon-defs.png", "label": "数据覆盖",
            "title": "这个 harness 不记录系统提示和工具 schema。",
            "body": "所以「工具定义 / 系统注入」的固定开销没有算进来；上面的占比只覆盖已落盘的消息。",
            "action": "想看完整固定开销，请在 ZCode 或 DeepSeek Harness 里运行；这两者会记录完整请求。",
            "metric": None,
        })

    # stable order, dedupe by title, drop the coverage card if we have 3 real ones
    real = [x for x in insights if x["label"] != "数据覆盖"]
    if len(real) >= 3:
        insights = real
    if not insights:
        insights.append({
            "severity": "info", "icon": "icon-pearl.png", "label": "下一步",
            "title": "这一轮没有明显的大头。",
            "body": "上下文分布比较均匀，或者数据覆盖不足。",
            "action": "先看完整账单；需要更细的分析时，再运行一次。",
            "metric": None,
        })
    return insights[:3]


def group_detail(group, by_key):
    if not group.get("recorded"):
        return "harness 未落盘"
    if group["key"] == "tool_results":
        c = by_key.get("tool_results") or {}
        top = c.get("top_item") or {}
        if top.get("chars"):
            return "%s tok · 最大 %s %s 字符" % (
                _fmt_int(group.get("tokens")), top.get("tool_name") or "tool", _fmt_int(top["chars"]))
    if group["key"] == "tool_definitions":
        c = by_key.get("tool_definitions") or {}
        n = (c.get("top_item") or {}).get("count") or c.get("count")
        return "%s tok · %s 个工具" % (_fmt_int(group.get("tokens")), n or "—")
    if group["key"] == "user_input":
        return "%s tok · %s 条" % (_fmt_int(group.get("tokens")), group.get("count") or 0)
    return "%s tok" % _fmt_int(group.get("tokens"))
