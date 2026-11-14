# -*- coding: utf-8 -*-
"""ai-fish scene state machine & snapshot time-machine.

Key capabilities:
1. Three-State PATCH semantics for scene / resume.md:
   - undefined / omitted: retain existing state (continuity)
   - empty string "" / [] / null: explicitly clear (wipe out resolved actions/tensions)
   - non-empty value: overwrite / update
2. 10-step FIFO snapshot rollback time-machine stack.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import INDEX, RESUME_MAX_CHARS, RESUME_PATH, atomic_write, ensure_dirs, iso, read_text

HISTORY_DIR = INDEX / "resume-history"
MAX_HISTORY = 10


def parse_resume_md(text: str) -> dict[str, Any]:
    """Parse resume.md markdown into structured dictionary."""
    data: dict[str, Any] = {
        "meta": {},
        "doing": "",
        "decided": [],
        "next": [],
        "pending": "",
    }
    if not text.strip():
        return data

    lines = text.splitlines()
    section = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- 归档时间："):
            data["meta"]["archivedAt"] = stripped.replace("- 归档时间：", "").strip()
            continue
        if stripped.startswith("- 对应日记："):
            data["meta"]["dailyFile"] = stripped.replace("- 对应日记：", "").strip()
            continue
        if stripped.startswith("- 本批事件："):
            data["meta"]["eventCount"] = stripped.replace("- 本批事件：", "").strip()
            continue

        if stripped.startswith("**在做什么**："):
            section = "doing"
            data["doing"] = stripped.replace("**在做什么**：", "").strip()
            continue
        if stripped.startswith("**已定**："):
            section = "decided"
            continue
        if stripped.startswith("**下一步**："):
            section = "next"
            continue
        if stripped.startswith("**悬着**："):
            section = "pending"
            data["pending"] = stripped.replace("**悬着**：", "").strip()
            continue

        if section in ("decided", "next"):
            m = re.match(r"^(\d+\.|\-)\s+(.*)$", stripped)
            if m:
                data[section].append(m.group(2).strip())
            elif stripped and data[section]:
                data[section][-1] += " " + stripped
        elif section in ("doing", "pending") and stripped and not stripped.startswith("---") and not stripped.startswith("#"):
            if data[section]:
                data[section] += " " + stripped
            else:
                data[section] = stripped

    return data


def format_resume_md(data: dict[str, Any]) -> str:
    """Format structured scene data into resume.md markdown format."""
    now_iso = iso()
    parts = [
        "# 现场快照（归档/状态机维护；供下个会话启动）\n",
        f"- 更新时间：{now_iso}",
    ]
    if data.get("meta", {}).get("dailyFile"):
        parts.append(f"- 对应日记：{data['meta']['dailyFile']}")
    if data.get("meta", {}).get("eventCount"):
        parts.append(f"- 本批事件：{data['meta']['eventCount']}")

    parts.append("\n---\n")

    doing = (data.get("doing") or "").strip()
    parts.append(f"**在做什么**：{doing if doing else '暂无指定主线任务。'}\n")

    parts.append("**已定**：")
    decided = data.get("decided") or []
    if decided:
        for idx, item in enumerate(decided, 1):
            parts.append(f"{idx}. {item}")
    else:
        parts.append("无新增已定事项。")
    parts.append("")

    parts.append("**下一步**：")
    next_items = data.get("next") or []
    if next_items:
        for idx, item in enumerate(next_items, 1):
            parts.append(f"{idx}. {item}")
    else:
        parts.append("无下一步计划。")
    parts.append("")

    pending = (data.get("pending") or "").strip()
    parts.append(f"**悬着**：\n{pending if pending else '无阻塞项。'}\n")

    res = "\n".join(parts)
    if len(res) > RESUME_MAX_CHARS:
        res = res[: RESUME_MAX_CHARS - 60] + "\n\n…[截断以满足上限]\n"
    return res


def push_history_snapshot(text: str, reason: str = "更新前备份") -> Path:
    """Push current resume.md text to 10-step FIFO history stack."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not text.strip():
        return RESUME_PATH

    ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    snap_file = HISTORY_DIR / f"resume-{ts_slug}.md"
    header = f"<!-- REASON: {reason} | AT: {iso()} -->\n"
    snap_file.write_text(header + text, encoding="utf-8")

    # FIFO prune to MAX_HISTORY
    snaps = sorted(HISTORY_DIR.glob("resume-*.md"))
    while len(snaps) > MAX_HISTORY:
        oldest = snaps.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass

    return snap_file


def rollback_scene_snapshot() -> tuple[bool, str]:
    """Roll back resume.md to previous snapshot in history."""
    if not HISTORY_DIR.exists():
        return False, "无历史快照目录"
    snaps = sorted(HISTORY_DIR.glob("resume-*.md"))
    if not snaps:
        return False, "历史快照栈为空，无法回滚"

    target = snaps.pop()
    try:
        content = target.read_text(encoding="utf-8")
        # Strip header comment if present
        clean_content = re.sub(r"^<!--.*?-->\n?", "", content)
        atomic_write(RESUME_PATH, clean_content)
        target.unlink()
        return True, f"已成功回滚至快照 {target.name}"
    except Exception as exc:
        return False, f"回滚快照失败：{exc}"


def apply_scene_patch(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply 3-state PATCH semantics:

    - key not in patch: keep old
    - patch[key] == "" / None / [] / "无": explicitly clear
    - patch[key] has value: update
    """
    updated = json.loads(json.dumps(current))

    for key in ("doing", "pending"):
        if key in patch:
            val = patch[key]
            if val is None or val == "" or str(val).strip() in ("", "无", "null"):
                updated[key] = ""
            else:
                updated[key] = str(val).strip()

    for key in ("decided", "next"):
        if key in patch:
            val = patch[key]
            if val is None or val == "" or val == [] or str(val).strip() in ("", "无", "[]"):
                updated[key] = []
            elif isinstance(val, list):
                updated[key] = [str(x).strip() for x in val if str(x).strip()]
            elif isinstance(val, str):
                updated[key] = [s.strip() for s in val.split("\n") if s.strip()]

    return updated


def cmd_scene(args: argparse.Namespace) -> int:
    """CLI handler for mem.py scene."""
    ensure_dirs()
    if args.rollback:
        ok, msg = rollback_scene_snapshot()
        print(f"{'ROLLBACK_OK' if ok else 'ROLLBACK_FAIL'}: {msg}")
        return 0 if ok else 1

    if args.history:
        if not HISTORY_DIR.exists():
            print("SCENE_HISTORY: 暂无历史快照")
            return 0
        snaps = sorted(HISTORY_DIR.glob("resume-*.md"))
        print(f"SCENE_HISTORY: 共 {len(snaps)} 份历史快照")
        for s in snaps:
            first_line = ""
            try:
                first_line = s.read_text(encoding="utf-8").splitlines()[0]
            except Exception:
                pass
            print(f"  - {s.name} {first_line}")
        return 0

    cur_text = read_text(RESUME_PATH) if RESUME_PATH.exists() else ""
    cur_data = parse_resume_md(cur_text)

    if args.patch_json:
        try:
            patch = json.loads(args.patch_json)
        except json.JSONDecodeError as exc:
            print(f"FAIL: patch-json 无法解析：{exc}")
            return 1
        if cur_text:
            push_history_snapshot(cur_text, reason=args.reason or "CLI scene patch")
        next_data = apply_scene_patch(cur_data, patch)
        new_text = format_resume_md(next_data)
        atomic_write(RESUME_PATH, new_text)
        print("SCENE_PATCH_OK")
        print(new_text)
        return 0

    # Default: show scene
    print("--- SCENE STATE (resume.md) ---")
    print(cur_text or "(空)")
    return 0
