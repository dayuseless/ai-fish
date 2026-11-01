# -*- coding: utf-8 -*-
"""ai-fish todo aggregation, status ledger, and rollover."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta

from .core import (
    DAILY,
    TODO_DONE_PATH,
    MemError,
    append_jsonl,
    clip,
    ensure_dirs,
    iso,
    memory_lock,
    now,
    read_jsonl,
    read_text,
    session_id,
    today_str,
)

TODO_EVIDENCE_RE = re.compile(r"evt-\d{8}-\d{6}-[0-9a-f]{4}")


def _todo_key(text: str) -> str:
    """归一化待办文本，用于跨批次去重（忽略证据编号与空白差异）。"""
    return TODO_EVIDENCE_RE.sub("", text).strip().casefold()


def _iter_todo_blocks(text: str):
    """从日记正文中产出 (批次时间, [待办条目])；只读解析，不改写任何内容。"""
    lines = text.splitlines()
    total = len(lines)
    batch = ""
    i = 0
    while i < total:
        line = lines[i]
        m = re.match(r"^##\s+固化批次\s+(\S+)", line.strip())
        if m:
            batch = m.group(1)
            i += 1
            continue
        if line.strip().startswith("## 待办"):
            i += 1
            items: list[str] = []
            cur: str | None = None
            while i < total and not lines[i].startswith("## ") and not lines[i].startswith("# "):
                raw = lines[i]
                stripped = raw.strip()
                if stripped.startswith("- "):
                    if cur is not None:
                        items.append(cur)
                    cur = stripped[2:].strip()
                elif not stripped:
                    if cur is not None:
                        items.append(cur)
                        cur = None
                elif cur is not None and (raw.startswith("  ") or raw.startswith("\t")):
                    cur = f"{cur} {stripped}"
                elif cur is not None:
                    items.append(cur)
                    cur = None
                i += 1
            if cur is not None:
                items.append(cur)
            yield batch, [x for x in items if x and x.strip() not in ("（无）", "(无)", "-")]
            continue
        i += 1


def _todo_done_keys() -> dict[str, dict]:
    """已办账本：index/todo-done.jsonl（只追加，派生数据，不是权威记录）。"""
    rows, _errors = read_jsonl(TODO_DONE_PATH)
    out: dict[str, dict] = {}
    for obj in rows:
        key = str(obj.get("key", ""))
        if key:
            out[key] = obj
    return out


def _todo_row_key(row: dict) -> str:
    return f"{row['date']}|{_todo_key(row['text'])}"


def cmd_todo(args: argparse.Namespace) -> int:
    """汇总未完成待办：日记各批次「待办」段，最新的覆盖旧的重复项。

    只读为主：不判断待办是否已完成（那是语义问题，工具不猜）。完成动作走
    `todo --done N`，写进派生账本 index/todo-done.jsonl，不动日记原文。
    """
    ensure_dirs()
    done = _todo_done_keys()
    files = sorted(DAILY.glob("20??-??-??.md"))
    days = max(0, int(args.days))
    if getattr(args, "rollover", False):
        today = today_str()
        files = [p for p in files if p.stem < today]
    elif not args.all and days:
        cutoff = (now() - timedelta(days=days)).date().isoformat()
        files = [p for p in files if p.stem >= cutoff]

    rows: list[dict] = []
    for path in files:
        try:
            text = read_text(path)
        except MemError:
            continue
        for batch, items in _iter_todo_blocks(text):
            for item in items:
                rows.append({"date": path.stem, "batch": batch, "text": item})

    latest: dict[str, dict] = {}
    for row in rows:
        key = _todo_key(row["text"])
        if not key:
            continue
        latest[key] = row
    merged = sorted(latest.values(), key=lambda r: (r["date"], r["batch"]), reverse=True)
    if not args.include_done:
        merged = [r for r in merged if _todo_row_key(r) not in done]

    if args.done:
        picked = []
        for token in str(args.done).replace("，", ",").split(","):
            token = token.strip()
            if not token:
                continue
            if not token.isdigit() or not (1 <= int(token) <= len(merged)):
                raise MemError(f"--done 序号无效：{token}（范围 1-{len(merged)}）")
            picked.append(merged[int(token) - 1])
        if not picked:
            raise MemError("--done 没有可标记的序号")
        with memory_lock():
            for row in picked:
                append_jsonl(
                    TODO_DONE_PATH,
                    {
                        "key": _todo_row_key(row),
                        "text": clip(row["text"].replace("\n", " "), 200),
                        "date": row["date"],
                        "marked_at": iso(),
                        "session": session_id(),
                    },
                )
        print(f"DONE_OK {len(picked)} 条已标记（index/todo-done.jsonl）")
        for row in picked:
            print(f"   - [{row['date']}] {clip(row['text'], 80)}")
        merged = [r for r in merged if r not in picked]

    if args.json:
        print(json.dumps({"count": len(merged), "todos": merged}, ensure_ascii=False, indent=1))
        return 0

    if getattr(args, "rollover", False):
        scope = "滚转（今日之前未完成）"
    elif args.all or not days:
        scope = "全部"
    else:
        scope = f"近 {days} 天"
    hidden = 0 if args.include_done else len(done)
    note = f"，已办过滤 {hidden}" if hidden else ""
    print(f"TODO {scope} · {len(merged)} 条（原始 {len(rows)} 条{note}）")
    if not merged:
        print("NO_TODO")
        return 0
    for tag, row in enumerate(merged, 1):
        stamp = row["batch"][5:16].replace("T", " ") if len(row["batch"]) >= 16 else row["date"]
        text = clip(row["text"].replace("\n", " "), args.max_chars)
        mark = " (已办)" if _todo_row_key(row) in done else ""
        if getattr(args, "rollover", False):
            try:
                age = (now().date() - datetime.strptime(row["date"], "%Y-%m-%d").date()).days
                mark += f" ⏰{age}d"
            except ValueError:
                pass
        print(f"{tag:>2}. [{stamp}] {text}{mark}")
    return 0
