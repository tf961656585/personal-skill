#!/usr/bin/env python3
"""Render the context-whale report into the static v4 HTML template."""

import html
import os
import shutil
import time

ASSET_FILES = [
    "hero-bento.jpg", "avatar.png", "icon-tools.png", "icon-reason.png",
    "icon-defs.png", "icon-skills.png", "icon-pearl.png",
]

COLORS = {
    "tool_results": "#E87461", "assistant_reasoning": "#9CC9E8",
    "tool_definitions": "#A8DCC8", "tool_calls": "#F5D98F",
    "injection_skills": "#E58AA0", "system_prompt": "#8FA98F",
    "injection_agents": "#C5AE86", "injection_other": "#D9C6A5",
    "user_input": "#C9B8E8", "assistant_text": "#E0B84F",
    "injection_date": "#B9B0A0", "other_blocks": "#CFC7B8",
    "rest": "#F5D98F",
}
CAT_DESC = {
    "tool_results": "Bash / Read / Skill 等工具返回的内容",
    "assistant_reasoning": "推理内容，会随历史消息回传",
    "tool_definitions": "工具的参数 schema",
    "tool_calls": "助手发出的调用参数",
    "injection_skills": "可用 skill 的描述列表",
    "system_prompt": "行为规则、沟通规范、环境说明",
    "injection_agents": "可用 agent 类型描述",
    "injection_other": "当前目录、工具权限等运行时信息",
    "user_input": "你实际写下的话",
    "assistant_text": "鲸鱼娘对你说的话",
    "injection_date": "每次请求附带的当前日期",
    "other_blocks": "step-start 等非文本块",
}
SIGNAL = {
    "tool_results": ("高", "warn"), "assistant_reasoning": ("正常", "up"),
    "tool_definitions": ("高", "warn"), "rest": ("正常", "mute"),
    "user_input": ("较低", "low"),
}

ICONS = {
    "star": '<path d="M12 3l2.2 5.2L20 9l-4.2 3.4L17 18l-5-3.1L7 18l1.2-5.6L4 9l5.8-.8L12 3z"/>',
    "whale": '<path d="M4 16c3-4.6 7-6.6 11.6-6.6 3.4 0 6.3 1.1 8.8 3.2"/><path d="M24.4 12.6c1.2-1.2 2.3-1.8 3.4-1.9-.3 2.2-1.3 4-3.1 5.3.7 4.3-1.3 7.8-6 10.3-4.4 2.4-8.9 2.4-13.5 0"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
}
SVG_OPEN = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'


def E(v):
    return html.escape(str(v), quote=True)


def fmt_int(n):
    if n is None:
        return "—"
    return "{:,}".format(int(round(n)))


def fmt_pct(x, digits=1):
    if x is None:
        return "—"
    return ("%." + str(digits) + "f%%") % (x * 100.0)


def copy_assets(skill_dir, out_dir):
    src = os.path.join(skill_dir, "assets")
    dst = os.path.join(out_dir, "assets")
    os.makedirs(dst, exist_ok=True)
    missing = []
    for name in ASSET_FILES:
        s = os.path.join(src, name)
        if not os.path.exists(s):
            missing.append(name)
            continue
        shutil.copy2(s, os.path.join(dst, name))
    if missing:
        raise RuntimeError("assets_missing: " + ", ".join(missing))


def stat_card(icon, title, value, suffix, sub, chip, color, bar=None):
    bar_html = ""
    if bar is not None:
        bar_html = '<div class="bar"><i style="width:%.1f%%"></i></div>' % max(0.0, min(100.0, float(bar)))
    return (
        '<div class="stat" style="--chip:%s;--icon:%s">'
        '<div class="ico-wrap">%s%s</svg></div>'
        '<div class="k">%s</div><div class="v">%s <small>%s</small></div>'
        '%s<div class="s">%s</div></div>'
    ) % (chip, color, SVG_OPEN, ICONS[icon], E(title), E(value), E(suffix), bar_html, sub)


def build_stats(report):
    w = report.get("window") or {}
    u = report.get("usage") or {}
    used = w.get("used") or u.get("input_tokens")
    limit = w.get("limit")
    pct = w.get("pct")
    if pct is not None:
        sub = "%s 窗口的 <b>%.1f%%</b>" % (fmt_int(limit), pct)
    elif limit:
        sub = "窗口 %s" % fmt_int(limit)
    else:
        sub = "窗口上限未记录"
    cache = u.get("cache_hit_pct")
    cache_val = "%.1f" % cache if cache is not None else "—"
    cache_sub = "命中缓存，省钱但不缩短上下文" if cache is not None else "该 harness 未记录"
    calls = len(report.get("series") or [])
    series = report.get("series") or []
    calls_sub = ("%s → %s" % (fmt_int(series[0]), fmt_int(series[-1]))) if len(series) > 1 else "本次会话"
    return "".join([
        stat_card("star", "本轮上下文", fmt_int(used), "tok", sub,
                  "linear-gradient(150deg,rgba(246,166,149,.46),rgba(238,116,97,.16))", "#EE7462",
                  bar=pct),
        stat_card("whale", "缓存命中", cache_val, "%", cache_sub,
                  "linear-gradient(150deg,rgba(183,228,210,.58),rgba(140,205,180,.18))", "#4C9A7A"),
        stat_card("sliders", "模型调用", str(calls) if calls else "—", "次", calls_sub,
                  "linear-gradient(150deg,rgba(248,227,174,.64),rgba(230,196,120,.20))", "#C99A3E"),
    ])


def build_dist(report):
    cards = []
    for g in report.get("groups") or []:
        recorded = g.get("recorded")
        pct = fmt_pct(g.get("share"), 2 if g.get("key") == "user_input" else 1)
        cls = "dcard " + g.get("color", "rest")
        style = "" if recorded else ' style="filter:saturate(.35);opacity:.72"'
        extra = ""
        if g.get("key") == "user_input":
            if recorded and (g.get("tokens") or 0) == 0:
                extra = '<div class="tok">本轮窗口里没有你的话</div>'
            else:
                extra = '<div class="tok">%s tokens</div>' % (
                    fmt_int(g.get("tokens")) if recorded else "未记录")
        card = (
            '<div class="%s"%s><div class="chip"><img src="assets/%s" alt="" /></div>'
            '<div class="body"><div class="pct">%s</div><div class="lbl">%s</div>%s</div>'
            '<img class="art" src="assets/%s" alt="" aria-hidden="true" /></div>'
        ) % (cls, style, E(g["icon"]), E(pct), E(g["label"]), extra, E(g["icon"]))
        cards.append(card)
    return "".join(cards)


def build_gauge(report):
    w = report.get("window") or {}
    used = w.get("used")
    limit = w.get("limit")
    pct = w.get("pct")
    if pct is not None:
        pct = max(0.0, min(100.0, float(pct)))
        offset = 226.2 * (1.0 - pct / 100.0)
        svg = (
            '<svg viewBox="0 0 200 118" role="img" aria-label="上下文窗口已使用 %.1f%%">'
            '<defs><linearGradient id="wg" x1="0" y1="1" x2="1" y2="0">'
            '<stop offset="0" stop-color="#35DACB"/><stop offset=".55" stop-color="#17C5C0"/><stop offset="1" stop-color="#0FAFAD"/>'
            '</linearGradient></defs>'
            '<path d="M28 100 A72 72 0 0 1 172 100" fill="none" stroke="#ECE3D4" stroke-width="15" stroke-linecap="round"/>'
            '<path d="M28 100 A72 72 0 0 1 172 100" fill="none" stroke="url(#wg)" stroke-width="15" stroke-linecap="round" stroke-dasharray="226.2" stroke-dashoffset="%.1f"/>'
            '</svg>'
            '<div class="gauge-center"><b>%.1f<small>%%</small></b><span>已用 %s / %s</span></div>'
        ) % (pct, offset, pct, fmt_int(used), fmt_int(limit))
        under = "<b>还早，不用压缩。</b>" if pct < 60 else "<b>接近上限，建议压缩。</b>"
        hint = "真正值得优化的是便当内部的比例"
    else:
        svg = (
            '<svg viewBox="0 0 200 118" role="img" aria-label="窗口上限未记录">'
            '<path d="M28 100 A72 72 0 0 1 172 100" fill="none" stroke="#ECE3D4" stroke-width="15" stroke-linecap="round"/>'
            '</svg>'
            '<div class="gauge-center"><b>—</b><span>%s tokens</span></div>'
        ) % fmt_int(used)
        under = "<b>窗口上限未记录。</b>"
        hint = "只知道绝对量，不知道占比"
    return svg, under, hint


def build_mini(report):
    u = report.get("usage") or {}
    cache = u.get("cache_hit_pct")
    calls = len(report.get("series") or [])
    cache_v = ("%.1f<small>%%</small>" % cache) if cache is not None else "—"
    calls_v = ("%d<small> 次</small>" % calls) if calls else "—"
    return (
        '<div><div class="k">缓存命中</div><div class="v">%s</div></div>'
        '<div><div class="k">调用</div><div class="v">%s</div></div>'
    ) % (cache_v, calls_v)


SPARKS = [
    ('#E87461', 'M2 27 C30 24,44 20,66 22 S104 10,128 15 S168 6,198 8'),
    ('#4FB3A8', 'M2 25 C28 24,42 22,64 23 S102 18,126 19 S166 15,198 16'),
    ('#C99A3E', 'M2 22 C30 22,48 21,70 22 S108 20,132 21 S170 19,198 20'),
]


def build_insights(report):
    cards = []
    for i, ins in enumerate((report.get("insights") or [])[:3]):
        color, path = SPARKS[i % len(SPARKS)]
        icon = ins.get("icon") or "icon-pearl.png"
        if not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", icon)):
            icon = "icon-pearl.png"
        cards.append((
            '<div class="icard">'
            '<div class="ihead"><img src="assets/%s" alt="" /><span>%s</span></div>'
            '<h3>%s</h3><p>%s</p>'
            '<div class="spark"><svg viewBox="0 0 200 34" preserveAspectRatio="none">'
            '<defs><linearGradient id="sg%d" x1="0" y1="0" x2="1" y2="0">'
            '<stop offset="0" stop-color="%s" stop-opacity="0"/>'
            '<stop offset=".22" stop-color="%s" stop-opacity=".95"/>'
            '<stop offset=".82" stop-color="%s" stop-opacity=".95"/>'
            '<stop offset="1" stop-color="%s" stop-opacity="0"/>'
            '</linearGradient></defs>'
            '<path d="%s L198 34 L2 34 Z" fill="%s" opacity=".10"/>'
            '<path d="%s" fill="none" stroke="url(#sg%d)" stroke-width="2.2"/>'
            '</svg>'
            '<div class="delta">%s</div></div></div>'
        ) % (E(icon), E(ins.get("label") or "洞察"), E(ins.get("title") or ""),
             E(ins.get("body") or ""), i, color, color, color, color,
             path, color, path, i, E(ins.get("action") or "")))
    while len(cards) < 1:
        cards.append(
            '<div class="icard"><div class="ihead"><img src="assets/icon-pearl.png" alt="" /><span>下一步</span></div>'
            '<h3>这一轮没有明显的大头。</h3><p>先看完整账单，再决定下一步。</p>'
            '<div class="spark"><svg viewBox="0 0 200 34" preserveAspectRatio="none">'
            '<path d="M2 24 C40 24,80 22,120 23 S170 21,198 22" fill="none" stroke="#C99A3E" stroke-width="2" opacity=".55"/></svg>'
            '<div class="delta">—</div></div></div>')
    return "".join(cards[:3])


def build_table(report):
    rows = []
    for g in report.get("groups") or []:
        key = g.get("key")
        signal, cls = SIGNAL.get(key, ("—", "mute"))
        if not g.get("recorded"):
            signal, cls = "未记录", "mute"
        elif (g.get("tokens") or 0) == 0:
            signal, cls = ("不在窗口" if key == "user_input" else "无"), "mute"
        rows.append((
            '<tr><td><span class="sw" style="background:%s"></span>'
            '<span class="t-name">%s</span></td>'
            '<td class="num strong">%s</td><td class="num">%s</td>'
            '<td class="trend %s">%s</td></tr>'
        ) % (COLORS.get(key, "#ccc"), E(g.get("label")),
             E(fmt_pct(g.get("share"), 2 if key == "user_input" else 1) if g.get("recorded") else "—"),
             E(fmt_int(g.get("tokens")) if g.get("recorded") else "—"), cls, E(signal)))
    return "".join(rows)


def build_full_table(report):
    rows = []
    for c in report.get("categories") or []:
        recorded = c.get("recorded")
        rows.append((
            '<tr><td><span class="sw" style="background:%s"></span>'
            '<span class="t-name">%s</span></td><td class="cell-desc">%s</td>'
            '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
        ) % (COLORS.get(c["key"], "#ccc"), E(c.get("label")),
             E(CAT_DESC.get(c["key"], "")),
             E(fmt_int(c.get("tokens")) if recorded else "未记录"),
             E(fmt_pct(c.get("share"), 2) if recorded else "—"),
             E(str(c.get("count") or 0) if recorded else "—")))
    return "".join(rows)


def build_lede(report):
    w = report.get("window") or {}
    groups = {g["key"]: g for g in report.get("groups") or []}
    used = w.get("used")
    limit = w.get("limit")
    pct = w.get("pct")
    tool = groups.get("tool_results") or {}
    user = groups.get("user_input") or {}
    tool_s = fmt_pct(tool.get("share")) if tool.get("recorded") else "—"
    user_s = fmt_pct(user.get("share"), 2) if user.get("recorded") else "—"
    if user.get("recorded") and (user.get("tokens") or 0) == 0:
        tail = "而你的话已经滑出了本轮窗口。"
    else:
        tail = "而你真正说的话，只有 <b>%s</b>。" % user_s
    if pct is not None:
        return ("这一轮模型读到的上下文是 <b>%s tokens</b>，占 %s 窗口的 <b>%.1f%%</b>。<br>"
                "鲸鱼娘把它做成了便当：工具日志占 <b>%s</b>，%s"
                % (fmt_int(used), fmt_int(limit), pct, tool_s, tail))
    return ("这一轮已知上下文是 <b>%s tokens</b>；这个 harness 没有记录窗口上限。<br>"
            "在已落盘的消息里，工具结果占 <b>%s</b>，%s"
            % (fmt_int(used), tool_s, tail))


def render(report, out_dir, skill_dir):
    template_path = os.path.join(skill_dir, "templates", "report.html")
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()

    copy_assets(skill_dir, out_dir)
    gauge, under, hint = build_gauge(report)
    w = report.get("window") or {}
    used = w.get("used")
    pct = w.get("pct")
    title = "每一个上下文，<br>都有<em>故事</em>。"
    session = report.get("session") or {}
    sid = str(session.get("id") or "")
    model = session.get("model") or "unknown model"
    now = time.strftime("%m-%d %H:%M")
    date = time.strftime("%Y-%m-%d")
    user_group = next((g for g in report["groups"] if g["key"] == "user_input"), {})
    if user_group.get("recorded") and (user_group.get("tokens") or 0) == 0:
        dist_note = ("本轮请求里没有你的话，占比按 0 计；「调用与注入」合并了工具调用、"
                     "技能/系统注入与回复。")
    else:
        dist_note = ("「你的话」只有 %s，单独放一颗小珍珠；「调用与注入」合并了工具调用、"
                     "技能/系统注入与回复。") % fmt_pct(user_group.get("share"), 2)
    if report.get("fidelity") != "L1":
        dist_note = "该 harness 不记录系统提示/工具 schema；未记录项显示为「—」，占比只覆盖已落盘的消息。"
    elif not (report.get("coverage") or {}).get("system_prompt", True):
        dist_note = ("本轮请求是尾部窗口快照，系统提示未落盘；占比只覆盖捕获到的消息，"
                     "总量按真实 usage 校准。")

    page = tpl
    replacements = {
        "{{TITLE_HTML}}": title,
        "{{LEDE}}": build_lede(report),
        "{{STATS}}": build_stats(report),
        "{{DIST_COUNT}}": "5",
        "{{DIST_CARDS}}": build_dist(report),
        "{{DIST_NOTE}}": dist_note,
        "{{GAUGE}}": gauge,
        "{{GAUGE_UNDER}}": under,
        "{{GAUGE_HINT}}": hint,
        "{{MINI_STATS}}": build_mini(report),
        "{{INSIGHTS}}": build_insights(report),
        "{{INSIGHT_COUNT}}": str(max(1, min(3, len(report.get("insights") or [])))),
        "{{TABLE_ROWS}}": build_table(report),
        "{{FULL_TABLE_ROWS}}": build_full_table(report),
        "{{FULL_COUNT}}": str(len(report.get("categories") or []) or 12),
        "{{SESSION_SHORT}}": E(sid[:20]),
        "{{MODEL}}": E(model),
        "{{GENERATED_TIME}}": E(now),
        "{{DATE}}": E(date),
        "{{WINDOW_LABEL}}": (fmt_int(w.get("limit")) + " TOKENS") if w.get("limit") else "未记录",
        "{{DIST_HEAD}}": "5 个主要类别 · REAL SHARE" if report.get("fidelity") == "L1" else "5 个主要类别 · 已知占比",
    }
    for k, v in replacements.items():
        page = page.replace(k, v)

    html_path = os.path.join(out_dir, "context-whale.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    return html_path
