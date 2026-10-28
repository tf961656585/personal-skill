#!/usr/bin/env python3
"""Harness adapters for context-whale.

Each adapter turns a harness session into a normalized report. The renderer and
insight engine only see the normalized report, never harness-specific shapes.
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

CATEGORIES = [
    ("tool_results", "工具结果"),
    ("assistant_reasoning", "助手思考"),
    ("tool_definitions", "工具定义"),
    ("tool_calls", "工具调用"),
    ("injection_skills", "注入 · 技能清单"),
    ("system_prompt", "系统提示"),
    ("injection_agents", "注入 · 子代理清单"),
    ("injection_other", "注入 · 其他"),
    ("user_input", "用户输入"),
    ("assistant_text", "助手回复"),
    ("injection_date", "注入 · 日期"),
    ("other_blocks", "其他块"),
]
CATEGORY_LABELS = dict(CATEGORIES)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def text_of(content):
    """Flatten a harness content field into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float)):
        return str(content)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("thinking"), str):
                    parts.append(block["thinking"])
                elif isinstance(block.get("content"), (str, list)):
                    parts.append(text_of(block["content"]))
                elif block.get("type") in ("tool-result", "tool_result"):
                    continue
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        for key in ("text", "content", "message", "output"):
            if key in content:
                return text_of(content[key])
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def classify_user_text(text):
    """Split user-role messages into harness injections vs real user input."""
    low = text.lower()
    if "<system-reminder>" in text:
        if "following skills are available" in low or "available_skills" in low or "a skill is a reusable" in low:
            return "injection_skills"
        if "available agent types" in low or "agent_listing" in low:
            return "injection_agents"
        if "today's date" in low or "currentdate" in low:
            return "injection_date"
        return "injection_other"
    if "current runtime context" in low or "runtime-context" in low:
        return "injection_other"
    if "local-command-caveat" in low or "<command-name>" in low:
        return "injection_other"
    return "user_input"


def prompt_tokens(usage, cache_additive=True):
    """Prompt size of one call, across provider usage dialects.

    totalTokens - outputTokens is the portable definition when present. When it
    is absent, cache_additive controls whether cacheReadTokens is a separate
    bucket (DSH) or already included in inputTokens (ZCode).
    """
    if not isinstance(usage, dict):
        return None
    total = usage.get("totalTokens")
    out = usage.get("outputTokens")
    if isinstance(total, int) and isinstance(out, int) and total >= out:
        return total - out
    inp = usage.get("inputTokens")
    cache = usage.get("cacheReadTokens")
    if isinstance(inp, int):
        return inp + (cache if (cache_additive and isinstance(cache, int)) else 0)
    return None


def empty_report(harness, fidelity):
    return {
        "schema_version": "1.0",
        "tool_version": "0.0.4",
        "generated_at": now_iso(),
        "harness": harness,
        "fidelity": fidelity,
        "session": {},
        "window": {"limit": None, "used": None, "pct": None, "source": None},
        "usage": {"input_tokens": None, "cache_read_tokens": None, "cache_hit_pct": None,
                  "usage_source": "unknown", "thread_cumulative_tokens": None},
        "categories": [],
        "groups": [],
        "series": [],
        "insights": [],
        "coverage": {},
        "method": {},
        "events": [],  # consumed by finalize(), not serialized
    }


def lookup_zcode_window(model_id):
    path = os.path.expanduser("~/.zcode/v2/provider_config.json")
    try:
        data = json.load(open(path, "r", encoding="utf-8"))
    except Exception:
        return None

    found = []

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("modelId") == model_id:
                props = ((obj.get("config") or {}).get("properties") or {})
                if isinstance(props.get("contextWindow"), int):
                    found.append(props["contextWindow"])
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data)
    return max(found) if found else None


# ---------------------------------------------------------------- ZCode

def zcode_db():
    return os.path.expanduser("~/.zcode/cli/db/db.sqlite")


def zcode_sessions(cwd):
    db = zcode_db()
    if not os.path.exists(db):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=3)
        rows = con.execute(
            # Fork sessions carry a parent_id; they are still first-class chats.
            "select id, title, directory, time_updated, time_created, task_type, parent_id "
            "from session where directory = ? and task_type in ('interactive', 'fork') "
            "order by time_updated desc limit 30", (cwd,)
        ).fetchall()
        con.close()
    except Exception:
        return []
    out = []
    for sid, title, directory, updated, created, task_type, parent in rows:
        rollout = os.path.expanduser("~/.zcode/cli/rollout/model-io-%s.jsonl" % sid)
        if not os.path.exists(rollout):
            continue
        out.append({
            "harness": "zcode", "fidelity": "L1", "session": sid, "title": title,
            "cwd": directory, "updated": updated, "path": rollout,
            "task_type": task_type, "parent": parent,
        })
    return out


def analyze_zcode(session=None, cwd=None, path=None):
    if path is None and session and "/" in str(session):
        path, session = session, None
    if path is None:
        if session is None:
            candidates = zcode_sessions(cwd or os.getcwd())
            if not candidates:
                return None
            path = candidates[0]["path"]
            session = candidates[0]["session"]
        else:
            path = os.path.expanduser("~/.zcode/cli/rollout/model-io-%s.jsonl" % session)
    if not os.path.exists(path):
        return None

    report = empty_report("zcode", "L1")
    messages = []
    latest = None
    series = []
    records = 0
    has_full = False
    first_offset = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            qs = rec.get("querySource")
            if qs and qs not in ("main_turn", "main"):
                continue
            req = rec.get("request") or {}
            msgs = req.get("messages") or []
            kind = req.get("messagesKind")
            off = req.get("messageOffset") or 0
            if first_offset is None:
                first_offset = off
            if kind == "full":
                has_full = True
            if kind == "full" or not messages:
                messages = list(msgs)
            else:
                start = len(messages) - off
                if start >= 0:
                    messages.extend(msgs[start:])
                else:
                    messages = list(msgs)
            latest = rec
            records += 1
            usage = (rec.get("response") or {}).get("usage") or {}
            pt = prompt_tokens(usage, cache_additive=False)
            if isinstance(pt, int) and pt > 0:
                series.append(pt)

    if latest is None:
        return None

    req = latest.get("request") or {}
    tools = (req.get("body") or {}).get("tools") or []
    usage = (latest.get("response") or {}).get("usage") or {}
    used = prompt_tokens(usage, cache_additive=False)
    cache = usage.get("cacheReadTokens")
    model = (latest.get("model") or {}).get("modelId") or (req.get("body") or {}).get("model")
    session_id = latest.get("sessionId") or session or os.path.basename(path).replace("model-io-", "").replace(".jsonl", "")
    updated = latest.get("completedAt") or latest.get("startedAt")

    report["session"] = {"id": session_id, "path": path, "model": model, "updated": updated, "cwd": cwd}
    report["usage"] = {
        "input_tokens": used, "cache_read_tokens": cache,
        "cache_hit_pct": (cache / used * 100.0) if cache is not None and used else None,
        "usage_source": "per_call", "thread_cumulative_tokens": None,
    }
    limit = lookup_zcode_window(model) if model else None
    report["window"] = {
        "limit": limit, "used": used,
        "pct": (used / limit * 100.0) if used and limit else None,
        "source": "provider_config" if limit else "unknown",
    }
    has_system = any((m.get("role") == "system") for m in messages)
    report["coverage"] = {
        "system_prompt": has_system, "tool_definitions": bool(tools), "tool_results": True,
        "usage": "per_call", "full_request": has_full,
    }
    report["method"] = {
        "source": "ZCode rollout JSONL",
        "reconstruction": "full+tail" if has_full else ("tail-window" if (first_offset or 0) > 0 else "full"),
        "token_estimate": "CJK-aware char estimate calibrated to usage.inputTokens",
        "records": records,
    }

    if tools:
        report["events"].append(("tool_definitions", json.dumps(tools, ensure_ascii=False), {"count": len(tools)}))

    tool_counts = {}
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "tool":
            name = m.get("toolName") or "tool"
            tool_counts[name] = tool_counts.get(name, 0) + 1
            report["events"].append(("tool_results", text_of(content), {"tool_name": name, "count": 1}))
            continue
        if role in ("user", "system") and isinstance(content, list):
            text = text_of(content)
            key = "system_prompt" if role == "system" else classify_user_text(text)
            report["events"].append((key, text, {}))
            continue
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "reasoning":
                    report["events"].append(("assistant_reasoning", text_of(block.get("text")), {}))
                elif btype == "text":
                    report["events"].append(("assistant_text", text_of(block.get("text")), {}))
                else:
                    report["events"].append(("other_blocks", text_of(block), {}))
        elif isinstance(content, str):
            if role == "system":
                report["events"].append(("system_prompt", content, {}))
            elif role == "user":
                key = classify_user_text(content)
                report["events"].append((key, content, {}))
            elif role == "tool":
                name = m.get("toolName") or "tool"
                tool_counts[name] = tool_counts.get(name, 0) + 1
                report["events"].append(("tool_results", content, {"tool_name": name, "count": 1}))
        calls = m.get("toolCalls") or m.get("tool_calls") or []
        if calls:
            report["events"].append(("tool_calls", json.dumps(calls, ensure_ascii=False),
                                     {"count": len(calls)}))

    report["series"] = series
    report["_tool_counts"] = tool_counts
    return report


# ---------------------------------------------------------------- DSH

def dsh_encode_cwd(cwd):
    return "--" + cwd.strip("/").replace("/", "-") + "--"


def dsh_sessions(cwd):
    root = os.path.expanduser("~/.dsh/sessions")
    if not os.path.isdir(root):
        return []
    candidates = []
    exact = os.path.join(root, dsh_encode_cwd(cwd))
    latest = {}
    for path in glob.glob(os.path.join(exact, "*", "session.v*.jsonl.zstd")):
        sid = os.path.basename(os.path.dirname(path))
        m = re.search(r"session\.v(\d+)\.jsonl\.zstd$", path)
        ver = int(m.group(1)) if m else 0
        if sid not in latest or ver > latest[sid][0]:
            latest[sid] = (ver, path)
    for sid, (ver, path) in latest.items():
        candidates.append({
            "harness": "dsh", "fidelity": "L1",
            "session": sid,
            "title": os.path.basename(os.path.dirname(os.path.dirname(path))),
            "cwd": cwd, "updated": int(os.path.getmtime(path) * 1000),
            "path": path,
        })
    candidates.sort(key=lambda x: x.get("updated", 0), reverse=True)
    return candidates


def dsh_lines(path):
    zstd = shutil.which("zstd")
    if not zstd:
        raise RuntimeError("zstd_not_found")
    proc = subprocess.run([zstd, "-dc", path], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("zstd_failed: " + (proc.stderr or "")[:200])
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def analyze_dsh(path=None, session=None, cwd=None):
    if path is None:
        candidates = dsh_sessions(cwd or os.getcwd())
        if session:
            candidates = [c for c in candidates if c["session"] == session]
        if not candidates:
            return None
        path = candidates[0]["path"]
        session = candidates[0]["session"]
    if not os.path.exists(path):
        return None

    report = empty_report("dsh", "L1")
    report["session"] = {"id": session, "path": path, "model": None, "updated": None, "cwd": cwd}
    usage_seen = []
    series = []
    call_names = {}
    tool_counts = {}
    limit = None
    model = None
    sid = session
    updated = None
    sys_texts = []
    events = []

    for ev in dsh_lines(path):
        typ = ev.get("type")
        data = ev.get("data") or {}
        if typ == "session":
            sid = data.get("id") or ev.get("id") or sid
            report["session"]["cwd"] = data.get("cwd") or ev.get("cwd") or cwd
            updated = data.get("createdAt") or ev.get("createdAt")
        elif typ == "model/selection":
            model = data.get("model") or model
        elif typ == "system/message":
            msg = data.get("message") or {}
            sys_texts.append(text_of(msg.get("content")))
        elif typ == "user/message":
            content = data.get("content")
            key = classify_user_text(text_of(content))
            events.append((key, text_of(content), {}))
        elif typ == "assistant/message":
            msg = data.get("message") or {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "reasoning":
                    events.append(("assistant_reasoning", text_of(block.get("text")), {}))
                elif btype == "text":
                    events.append(("assistant_text", text_of(block.get("text")), {}))
                elif btype == "tool-call":
                    cid = block.get("id")
                    name = block.get("name") or "tool"
                    if cid:
                        call_names[cid] = name
                    events.append(("tool_calls", text_of(block.get("arguments")), {"count": 1}))
            u = data.get("usage") or {}
            pt = prompt_tokens(u)
            if isinstance(pt, int) and pt > 0:
                usage_seen.append(u)
                series.append(pt)
        elif typ == "usage":
            u = data.get("usage") or data
            pt = prompt_tokens(u)
            if isinstance(pt, int) and pt > 0:
                usage_seen.append(u)
                series.append(pt)
        elif typ == "tool/result":
            msg = data.get("message") or {}
            content = msg.get("content")
            cid = msg.get("toolCallId")
            texts = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, dict):
                texts.append(text_of(content))
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        cid = cid or block.get("toolCallId")
                        texts.append(text_of(block))
                    elif isinstance(block, str):
                        texts.append(block)
            name = call_names.get(cid, "tool")
            tool_counts[name] = tool_counts.get(name, 0) + 1
            events.append(("tool_results", "\n".join(t for t in texts if t), {"tool_name": name, "count": 1}))
        elif typ == "tool/call":
            cid = data.get("callId")
            name = data.get("name")
            if cid and name:
                call_names[cid] = name
        elif typ == "request/header":
            header = data.get("header") or {}
            config = header.get("config") or {}
            model = config.get("model") or model
            tools = header.get("tools") or []
            if tools:
                events.append(("tool_definitions", json.dumps(tools, ensure_ascii=False), {"count": len(tools)}))
        elif typ == "request/context":
            model = data.get("model") or model
            if isinstance(data.get("contextWindow"), int):
                limit = data["contextWindow"]
        if ev.get("time"):
            updated = ev["time"]

    if sys_texts:
        events.insert(0, ("system_prompt", "\n".join(sys_texts), {}))

    latest_usage = max(usage_seen, key=prompt_tokens) if usage_seen else {}
    used = prompt_tokens(latest_usage)
    cache = latest_usage.get("cacheReadTokens")
    report["session"] = {"id": sid, "path": path, "model": model, "updated": updated,
                         "cwd": report["session"].get("cwd") or cwd}
    report["usage"] = {
        "input_tokens": used, "cache_read_tokens": cache,
        "cache_hit_pct": (cache / used * 100.0) if cache is not None and used else None,
        "usage_source": "per_call", "thread_cumulative_tokens": None,
    }
    report["window"] = {
        "limit": limit, "used": used,
        "pct": (used / limit * 100.0) if used and limit else None,
        "source": "request/context" if limit else "unknown",
    }
    report["coverage"] = {
        "system_prompt": True, "tool_definitions": True, "tool_results": True,
        "usage": "per_call", "full_request": True,
    }
    report["method"] = {"source": "DSH session.v3/v4.jsonl.zstd event stream",
                        "token_estimate": "CJK-aware char estimate calibrated to usage.inputTokens"}
    report["events"] = events
    report["series"] = series
    report["_tool_counts"] = tool_counts
    return report


# ---------------------------------------------------------------- Claude Code

def claude_sessions(cwd):
    root = os.path.expanduser("~/.claude/projects")
    encoded = cwd.replace("/", "-")
    paths = glob.glob(os.path.join(root, encoded, "*.jsonl"))
    out = []
    for path in paths:
        out.append({
            "harness": "claude_code", "fidelity": "L2",
            "session": os.path.splitext(os.path.basename(path))[0],
            "title": os.path.basename(os.path.dirname(path)),
            "cwd": cwd, "updated": int(os.path.getmtime(path) * 1000), "path": path,
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def analyze_claude(path=None, session=None, cwd=None):
    if path is None:
        candidates = claude_sessions(cwd or os.getcwd())
        if session:
            candidates = [c for c in candidates if c["session"] == session]
        if not candidates:
            return None
        path = candidates[0]["path"]
        session = candidates[0]["session"]
    if not os.path.exists(path):
        return None

    report = empty_report("claude_code", "L2")
    events = []
    series = []
    latest_usage = None
    model = None
    tool_counts = {}
    call_names = {}
    sid = session or os.path.splitext(os.path.basename(path))[0]

    for rec in read_jsonl(path):
        typ = rec.get("type")
        msg = rec.get("message") or {}
        if typ == "user":
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        name = call_names.get(block.get("tool_use_id"), "tool")
                        tool_counts[name] = tool_counts.get(name, 0) + 1
                        events.append(("tool_results", text_of(block.get("content")),
                                       {"tool_name": name, "count": 1}))
                    elif block.get("type") == "text":
                        key = classify_user_text(text_of(block.get("text")))
                        events.append((key, text_of(block.get("text")), {}))
            elif isinstance(content, str):
                key = classify_user_text(content)
                events.append((key, content, {}))
        elif typ == "assistant":
            model = msg.get("model") or model
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "thinking":
                    events.append(("assistant_reasoning", text_of(block.get("thinking")), {}))
                elif btype == "text":
                    events.append(("assistant_text", text_of(block.get("text")), {}))
                elif btype == "tool_use":
                    name = block.get("name") or "tool"
                    if block.get("id"):
                        call_names[block.get("id")] = name
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    events.append(("tool_calls", json.dumps(block.get("input"), ensure_ascii=False),
                                   {"count": 1, "tool_name": name}))
            if isinstance(msg.get("usage"), dict):
                latest_usage = msg["usage"]
                u = msg["usage"]
                total = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
                if total:
                    series.append(total)
        elif typ == "attachment":
            att = rec.get("attachment") or {}
            if att.get("type") == "skill_listing":
                events.append(("injection_skills", text_of(att.get("content")), {}))
            else:
                events.append(("injection_other", text_of(att.get("content")), {}))
        elif typ == "system":
            if rec.get("subtype") == "local_command":
                events.append(("injection_other", text_of(rec.get("content")), {}))

    used = None
    cache = None
    if latest_usage:
        used = (latest_usage.get("input_tokens") or 0) + \
               (latest_usage.get("cache_read_input_tokens") or 0) + \
               (latest_usage.get("cache_creation_input_tokens") or 0)
        cache = latest_usage.get("cache_read_input_tokens")
    if not used:
        used = None

    limit = None
    if model:
        limit = 1000000 if "1m" in model.lower() else 200000

    report["session"] = {"id": sid, "path": path, "model": model,
                         "updated": int(os.path.getmtime(path) * 1000), "cwd": cwd}
    report["usage"] = {
        "input_tokens": used, "cache_read_tokens": cache,
        "cache_hit_pct": (cache / used * 100.0) if cache is not None and used else None,
        "usage_source": "per_call" if used else "estimated", "thread_cumulative_tokens": None,
    }
    report["window"] = {
        "limit": limit, "used": used,
        "pct": (used / limit * 100.0) if used and limit else None,
        "source": "assumed_model_limit" if limit else "unknown",
    }
    report["coverage"] = {
        "system_prompt": False, "tool_definitions": False, "tool_results": True,
        "usage": "per_call" if used else "estimated", "full_request": False,
    }
    report["method"] = {"source": "Claude Code project JSONL transcript",
                        "token_estimate": "CJK-aware char estimate" + (" calibrated to assistant usage" if used else ""),
                        "note": "system prompt and tool schemas are not in the transcript"}
    report["events"] = events
    report["series"] = series
    report["_tool_counts"] = tool_counts
    return report


# ---------------------------------------------------------------- Codex

def codex_state_db():
    return os.path.expanduser("~/.codex/state_5.sqlite")


def codex_history_db():
    return os.path.expanduser("~/.codex/thread_history_1.sqlite")


def codex_sessions(cwd):
    db = codex_state_db()
    if not os.path.exists(db):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=3)
        rows = con.execute(
            "select id, cwd, model, tokens_used, created_at_ms, updated_at_ms, name, first_user_message "
            "from threads where cwd = ? order by updated_at_ms desc limit 30", (cwd,)
        ).fetchall()
        con.close()
    except Exception:
        return []
    return [{
        "harness": "codex", "fidelity": "L2", "session": r[0], "cwd": r[1],
        "model": r[2], "updated": r[5], "title": r[6] or (r[7] or "")[:60],
        "path": codex_history_db(),
    } for r in rows]


def analyze_codex(thread_id=None, cwd=None, session=None, path=None):
    thread_id = thread_id or session
    if not thread_id:
        candidates = codex_sessions(cwd or os.getcwd())
        if not candidates:
            return None
        thread_id = candidates[0]["session"]
    state = codex_state_db()
    history = codex_history_db()
    if not os.path.exists(state) or not os.path.exists(history):
        return None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % state, uri=True, timeout=3)
        row = con.execute(
            "select id, cwd, model, tokens_used, created_at_ms, updated_at_ms, name, first_user_message "
            "from threads where id = ?", (thread_id,)
        ).fetchone()
        con.close()
    except Exception:
        row = None
    if not row:
        return None
    tid, cwd0, model, tokens_used, created, updated, name, first = row

    try:
        con = sqlite3.connect("file:%s?mode=ro" % history, uri=True, timeout=3)
        rows = con.execute(
            "select item_type, item_json from thread_items where thread_id = ? order by created_at_ms asc",
            (tid,)
        ).fetchall()
        con.close()
    except Exception:
        rows = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % state, uri=True, timeout=3)
        tool_rows = con.execute(
            "select name, description, input_schema from thread_dynamic_tools where thread_id = ?",
            (tid,)
        ).fetchall()
        con.close()
    except Exception:
        tool_rows = []

    events = []
    tool_counts = {}
    for item_type, item_json in rows:
        try:
            item = json.loads(item_json)
        except Exception:
            continue
        if item_type == "userMessage":
            events.append(("user_input", text_of(item.get("text") or item.get("content")), {}))
        elif item_type == "agentMessage":
            events.append(("assistant_text", text_of(item.get("text")), {}))
        elif item_type == "reasoning":
            summary = item.get("summary")
            text = text_of(summary) or text_of(item.get("content"))
            events.append(("assistant_reasoning", text, {}))
        elif item_type == "commandExecution":
            cmd = item.get("command") or ""
            out = item.get("aggregatedOutput") or ""
            tool_counts["shell"] = tool_counts.get("shell", 0) + 1
            events.append(("tool_calls", cmd, {"count": 1, "tool_name": "shell"}))
            events.append(("tool_results", out, {"count": 1, "tool_name": "shell"}))
        elif item_type in ("fileChange", "webSearch", "mcpToolCall", "dynamicToolCall"):
            name = item.get("name") or item_type
            tool_counts[name] = tool_counts.get(name, 0) + 1
            events.append(("tool_calls", json.dumps(item, ensure_ascii=False)[:4000],
                           {"count": 1, "tool_name": name}))
            events.append(("tool_results", json.dumps(item.get("result") or item.get("output") or "",
                                                      ensure_ascii=False)[:12000],
                           {"count": 1, "tool_name": name}))
        elif item_type == "contextCompaction":
            events.append(("injection_other", text_of(item), {}))
        elif item_type == "plan":
            events.append(("assistant_text", text_of(item), {}))
        elif item_type == "imageGeneration":
            events.append(("other_blocks", text_of(item), {}))

    if tool_rows:
        tools = [{"name": n, "description": d, "input_schema": s} for n, d, s in tool_rows]
        events.insert(0, ("tool_definitions", json.dumps(tools, ensure_ascii=False),
                          {"count": len(tools)}))

    report = empty_report("codex", "L2")
    report["session"] = {"id": tid, "path": history, "model": model,
                         "updated": updated, "cwd": cwd0 or cwd,
                         "title": name or first}
    report["usage"] = {
        "input_tokens": None, "cache_read_tokens": None, "cache_hit_pct": None,
        "usage_source": "estimated", "thread_cumulative_tokens": tokens_used,
    }
    report["window"] = {"limit": None, "used": None, "pct": None,
                        "source": "not_recorded"}
    report["coverage"] = {
        "system_prompt": False, "tool_definitions": "partial" if tool_rows else False,
        "tool_results": True, "usage": "estimated", "full_request": False,
    }
    report["method"] = {"source": "Codex thread_history_1.sqlite + state_5.sqlite",
                        "token_estimate": "CJK-aware char estimate; thread cumulative tokens reported separately",
                        "note": "built-in tool schemas and system prompt are not recorded; tokens_used is cumulative, not current context"}
    report["events"] = events
    report["series"] = []
    report["_tool_counts"] = tool_counts
    return report


# ---------------------------------------------------------------- Pi / OpenClaw

def pi_sessions(cwd):
    roots = [
        os.path.expanduser("~/.pi/sessions"),
        os.path.expanduser("~/.openclaw/agents/main/sessions"),
        os.path.expanduser("~/.openclaw/agents/*/sessions"),
    ]
    paths = []
    for root in roots:
        paths.extend(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
    out = []
    for path in sorted(set(paths)):
        try:
            first = json.loads(open(path, encoding="utf-8", errors="replace").readline())
        except Exception:
            continue
        if first.get("type") != "session":
            continue
        if first.get("cwd") and cwd and first.get("cwd") != cwd:
            continue
        out.append({
            "harness": "pi", "fidelity": "L2",
            "session": first.get("id") or os.path.splitext(os.path.basename(path))[0],
            "title": os.path.basename(os.path.dirname(path)),
            "cwd": first.get("cwd") or cwd,
            "updated": int(os.path.getmtime(path) * 1000), "path": path,
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def analyze_pi(path=None, session=None, cwd=None):
    if path is None:
        candidates = pi_sessions(cwd or os.getcwd())
        if session:
            candidates = [c for c in candidates if c["session"] == session]
        if not candidates:
            return None
        path = candidates[0]["path"]
        session = candidates[0]["session"]
    if not os.path.exists(path):
        return None

    report = empty_report("pi", "L2")
    events = []
    usage = None
    model = None
    for rec in read_jsonl(path):
        typ = rec.get("type")
        if typ == "session":
            session = rec.get("id") or session
        elif typ == "message":
            msg = rec.get("message") or {}
            role = msg.get("role")
            content = msg.get("content")
            text = text_of(content)
            if role == "user":
                events.append((classify_user_text(text), text, {}))
            elif role == "assistant":
                events.append(("assistant_text", text, {}))
            elif role == "tool":
                events.append(("tool_results", text, {"tool_name": "tool", "count": 1}))
            if isinstance(msg.get("usage"), dict):
                usage = msg["usage"]
                model = msg.get("model") or model
    used = None
    cache = None
    if usage:
        used = (usage.get("input") or 0) + (usage.get("cacheRead") or 0)
        cache = usage.get("cacheRead")
    report["session"] = {"id": session, "path": path, "model": model,
                         "updated": int(os.path.getmtime(path) * 1000), "cwd": cwd}
    report["usage"] = {
        "input_tokens": used, "cache_read_tokens": cache,
        "cache_hit_pct": (cache / used * 100.0) if cache is not None and used else None,
        "usage_source": "per_call" if used else "estimated", "thread_cumulative_tokens": None,
    }
    report["window"] = {"limit": None, "used": used, "pct": None, "source": "not_recorded"}
    report["coverage"] = {
        "system_prompt": False, "tool_definitions": False, "tool_results": True,
        "usage": "per_call" if used else "estimated", "full_request": False,
    }
    report["method"] = {"source": "Pi/OpenClaw session JSONL",
                        "token_estimate": "CJK-aware char estimate" + (" calibrated to usage" if used else ""),
                        "note": "system prompt and tool schemas are not recorded"}
    report["events"] = events
    report["series"] = []
    report["_tool_counts"] = {}
    return report


# ---------------------------------------------------------------- registry

ADAPTERS = {
    "zcode": {"fidelity": "L1", "discover": zcode_sessions, "analyze": analyze_zcode},
    "dsh": {"fidelity": "L1", "discover": dsh_sessions, "analyze": analyze_dsh},
    "claude_code": {"fidelity": "L2", "discover": claude_sessions, "analyze": analyze_claude},
    "codex": {"fidelity": "L2", "discover": codex_sessions, "analyze": analyze_codex},
    "pi": {"fidelity": "L2", "discover": pi_sessions, "analyze": analyze_pi},
}

HARNESS_ALIASES = {
    "zcode": "zcode", "dsh": "dsh", "deepseek": "dsh",
    "claude": "claude_code", "claude_code": "claude_code", "claude-code": "claude_code",
    "codex": "codex", "chatgpt": "codex", "chatgptapp": "codex",
    "pi": "pi", "openclaw": "pi",
}


def resolve_harness(name):
    return HARNESS_ALIASES.get((name or "").lower(), name)


def discover_all(cwd):
    out = []
    for name, meta in ADAPTERS.items():
        try:
            out.extend(meta["discover"](cwd))
        except Exception:
            continue
    out.sort(key=lambda x: x.get("updated", 0), reverse=True)
    return out


def analyze_session(harness=None, session=None, path=None, cwd=None):
    cwd = cwd or os.getcwd()
    harness = resolve_harness(harness)
    if session and not path and ("/" in str(session) or str(session).endswith((".jsonl", ".zstd"))):
        path, session = session, None
    if harness and harness in ADAPTERS:
        return ADAPTERS[harness]["analyze"](session=session, path=path, cwd=cwd)
    if session or path:
        # An explicit target must fail closed: never substitute another session.
        for name in ("zcode", "dsh", "claude_code", "codex", "pi"):
            try:
                report = ADAPTERS[name]["analyze"](session=session, path=path, cwd=cwd)
                if report:
                    return report
            except Exception:
                continue
        return None
    if harness in (None, "", "auto"):
        # Prefer the harness that has a session for this cwd, in fidelity order.
        for name in ("zcode", "dsh", "claude_code", "codex", "pi"):
            try:
                candidates = ADAPTERS[name]["discover"](cwd)
                if candidates:
                    return ADAPTERS[name]["analyze"](session=candidates[0]["session"], cwd=cwd)
            except Exception:
                continue
    return None
