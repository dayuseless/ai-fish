# -*- coding: utf-8 -*-
"""ai-fish session lifecycle: session-start, resume scene, meta, and sync-resume."""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

from .core import (
    ALLOWED_SEAL_STATUS,
    BASE,
    RESUME_MAX_CHARS,
    RESUME_PATH,
    WORKSPACE,
    MemError,
    atomic_write,
    clip,
    ensure_dirs,
    iso,
    load_config,
    load_state,
    memory_lock,
    now,
    read_text,
    rel_posix,
    save_state,
    session_id,
)
from .seal import check_seal, print_seal
from .storage import pending_events


def _touch_session_state() -> dict:
    try:
        with memory_lock(timeout=5.0):
            state = load_state()
            state["lastSession"] = {
                "id": session_id(),
                "startedAt": iso(),
                "cwd": str(WORKSPACE),
            }
            save_state(state)
            return state
    except MemError as exc:
        print(f"WARN: 本次不更新 state（{exc}）；记忆读取继续进行。")
        try:
            return load_state()
        except MemError:
            return {}


def _print_transcript_hint() -> None:
    try:
        from .transcript import _same_workspace, _session_files

        transcripts = _session_files()
        same_others = [
            p
            for p in transcripts
            if p.parent.name != session_id() and _same_workspace(p)
        ]
        if same_others:
            print(
                f"TRANSCRIPT: 同一工作区发现 {len(same_others)} 个其他 DSH 会话记录；"
                "怀疑有遗漏时用 `mem.py transcript --session previous` 只读查看上一会话摘要。"
            )
    except Exception:  # noqa: BLE001 - hint only, never block startup
        pass


def _resume_age_days(text: str) -> float | None:
    match = re.search(r"归档时间：(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
    if not match:
        return None
    try:
        then = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S").astimezone()
    except ValueError:
        return None
    return max(0.0, (now() - then).total_seconds() / 86400)


def _print_resume(pending_count: int) -> None:
    """打印上次归档留下的现场快照；这是给下个会话的快速启动面。"""
    print("--- RESUME (上次归档现场) ---")
    if not RESUME_PATH.exists():
        print("（还没有现场快照；下次 commit-daily 时用 --scene-file 写一段）")
        print()
        return
    text = read_text(RESUME_PATH).strip()
    if not text:
        print("（现场快照为空）")
        print()
        return
    print(clip(text, RESUME_MAX_CHARS + 400))
    age = _resume_age_days(text)
    if age is not None and age > 2:
        print(f"WARN: 现场快照已 {age:.1f} 天未更新，可能落后于当前实际；以日记/原始事件为准。")
    if pending_count:
        print(f"WARN: 还有 {pending_count} 条未固化事件，现场快照可能没包含它们。")
    print()


def _session_start_brief(cfg: dict) -> int:
    meta_path = BASE / "META.md"
    print("--- BRIEF (元文档模式) ---")
    print(f"RULES: {cfg['canonical_rules']}（权威安全规则；涉及权限/删除/规则变更时读全文）")
    print(f"META : {rel_posix(meta_path)}（先读元文档；按触发索引读取细则）")
    print()

    pending = pending_events(report_errors=True)
    print(f"--- PENDING RAW EVENTS: {len(pending)} ---")
    for path, lineno, obj in pending[:20]:
        text = str(obj.get("text", "")).replace("\n", " ")
        print(f"  [{obj.get('id')}] {obj.get('ts')} {obj.get('kind')}: {text[:160]}")
    if len(pending) > 20:
        print(f"  ... 还有 {len(pending) - 20} 条，运行 `mem.py pending --full` 查看。")
    if pending:
        print("NEXT: 按 AGENTS.md 处理这些待固化事件。")
    else:
        print("PENDING: 0")
    print()

    _print_resume(len(pending))

    state = _touch_session_state()
    print("--- STATE ---")
    print(f"  last consolidation: {state.get('lastConsolidation')}")
    print()
    print("NEXT: 先看 RESUME 接手现场；再读 META.md，按触发读取 SELF/USER/MEMORY/SPEC/日记；正常响应用户。")
    _print_transcript_hint()
    return 0


def cmd_session_start(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    info = check_seal(cfg)
    print("===== AI-FISH SESSION START =====")
    print(f"time    : {iso()}")
    print(f"session : {session_id()}")
    print(f"workspace: {WORKSPACE}")
    print_seal(info)
    print()
    if info["status"] not in ALLOWED_SEAL_STATUS:
        print("STOP: 规则完整性不可信。不要写入记忆；向用户报告并等待处理。")
        pending = pending_events(report_errors=True)
        print(f"PENDING (未处理原始事件): {len(pending)}")
        for path, lineno, obj in pending[:20]:
            print(f"  [{obj.get('id')}] {obj.get('kind')}: {str(obj.get('text', ''))[:100]}")
        return 2

    if info["status"] == "MIRROR_MISMATCH":
        print("WARN: 工作区镜像漂移；权威文件可信。可运行 `mem.py sync-rules` 修复镜像。\n")

    if getattr(args, "brief", False):
        return _session_start_brief(cfg)

    rules_text = read_text(Path(cfg["canonical_rules"]))
    print("--- RULES (canonical) ---")
    print(clip(rules_text, 12000))
    print()

    for name in ("SELF.md", "USER.md", "MEMORY.md"):
        path = BASE / name
        print(f"--- {name} ---")
        if path.exists():
            print(clip(read_text(path), 12000))
        else:
            print(f"MISSING: {path}")
        print()

    from .core import DAILY

    dailies = sorted(DAILY.glob("20??-??-??.md"))
    print("--- LATEST DAILY ---")
    if dailies:
        latest = dailies[-1]
        lines = read_text(latest).splitlines()
        print(f"# {rel_posix(latest)} (last {min(120, len(lines))} lines)")
        print(clip("\n".join(lines[-120:]), 10000))
    else:
        print("(none)")
    print()

    pending = pending_events(report_errors=True)
    print(f"--- PENDING RAW EVENTS: {len(pending)} ---")
    for path, lineno, obj in pending[:20]:
        text = str(obj.get("text", "")).replace("\n", " ")
        print(f"  [{obj.get('id')}] {obj.get('ts')} {obj.get('kind')}: {text[:160]}")
    if len(pending) > 20:
        print(f"  ... 还有 {len(pending) - 20} 条，运行 `mem.py pending --full` 查看。")
    if pending:
        print("NEXT: 先按 AGENTS.md 固化这些事件，或在本次会话结束前固化。")

    state = _touch_session_state()
    print("--- STATE ---")
    print(f"  last consolidation: {state.get('lastConsolidation')}")

    print("\nNEXT: 读取 RULES 后正常响应用户；重要事件用 `mem.py note` 记录。")
    _print_transcript_hint()
    return 0


def cmd_meta(args: argparse.Namespace) -> int:
    path = BASE / "META.md"
    if args.path:
        print(path)
        return 0
    if not path.is_file():
        raise MemError("META.md 不存在")
    print(read_text(path))
    return 0


def cmd_sync_resume(args: argparse.Namespace) -> int:
    """当存在未固化事件时，刷新现场快照（resume.md），避免跨会话断层。

    不做完整固化（commit-daily），只把 pending 事件的摘要补进现场快照，
    保留原有的「在做/已定/下一步」，把 pending 列表写进「悬着」。
    """
    ensure_dirs()
    pending = pending_events(report_errors=True)

    if not pending and not getattr(args, "force", False):
        print("SYNC_RESUME_NOOP: 没有未固化事件，现场快照无需更新")
        return 0

    old_text = read_text(RESUME_PATH) if RESUME_PATH.exists() else ""
    preserved: dict[str, str] = {}
    for heading in ("## 在做", "## 已定", "## 下一步"):
        m = re.search(
            rf"({re.escape(heading)}\s*\n[\s\S]*?)(?=\n## |\Z)",
            old_text,
        )
        if m:
            preserved[heading] = m.group(1).rstrip()

    pending_lines: list[str] = []
    for _, _, obj in pending[:15]:
        text = str(obj.get("text", "")).replace("\n", " ")[:120]
        pending_lines.append(f"- [{obj.get('id')}] {obj.get('kind')}: {text}")
    if len(pending) > 15:
        pending_lines.append(f"- … 还有 {len(pending) - 15} 条")
    pending_block = "\n".join(pending_lines) if pending_lines else "- （无）"

    ts = iso()
    parts: list[str] = [
        "# 现场快照（sync-resume 自动刷新）\n",
        f"- 刷新时间：{ts}",
        f"- 未固化事件：{len(pending)} 条",
        "",
        "---",
        "",
    ]
    for heading in ("## 在做", "## 已定", "## 下一步"):
        if heading in preserved:
            parts.append(preserved[heading])
            parts.append("")

    parts.append("## 悬着（含未固化事件）")
    parts.append("")
    parts.append(pending_block)
    parts.append("")

    resume_text = "\n".join(parts)
    if len(resume_text) > RESUME_MAX_CHARS:
        resume_text = resume_text[: RESUME_MAX_CHARS - 60] + "\n\n…[截断以满足 1200 字上限]\n"

    with memory_lock():
        atomic_write(RESUME_PATH, resume_text)

    print(f"SYNC_RESUME_OK pending={len(pending)} chars={len(resume_text)}")
    return 0
