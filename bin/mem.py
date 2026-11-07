#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai-fish: lightweight cross-session memory tools (CLI entry point).

Modularized architecture:
  * lib.core: paths, lock, atomicity, state, and jsonl primitives
  * lib.seal: rules seal verification and sync
  * lib.storage: raw events, commit-daily, snapshots, and restore
  * lib.session: session-start, resume scene, and sync-resume
  * lib.todo: todo aggregation, status ledger, and rollover
  * lib.grant: oral approvals tracking
  * lib.promote: long-term memory promotion candidates detection
  * lib.search: full-text search across memory store
  * lib.transcript: read-only DSH session frame decoding
  * lib.audit: status, verify, and audit
  * lib.db: lightweight sqlite database for long-term memory & fast indexing
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Robust import resolution for both in-tree runs and isolated test copies
_BIN_DIR = Path(__file__).resolve().parent
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))

try:
    from lib.audit import cmd_audit, cmd_status, cmd_verify
    from lib.core import KINDS, MemError
    from lib.db import cmd_db
    from lib.grant import cmd_grant
    from lib.promote import cmd_promote_check
    from lib.search import cmd_search
    from lib.seal import cmd_sync_rules
    from lib.session import cmd_meta, cmd_session_start, cmd_sync_resume
    from lib.storage import cmd_commit_daily, cmd_init, cmd_note, cmd_pending, cmd_redact, cmd_restore, cmd_snapshot
    from lib.todo import cmd_todo
    from lib.transcript import cmd_transcript
    from lib.mailbox import cmd_mailbox
except ModuleNotFoundError:
    # Fallback import resolution
    pass
    from lib.audit import cmd_audit, cmd_status, cmd_verify
    from lib.core import KINDS, MemError
    from lib.db import cmd_db
    from lib.grant import cmd_grant
    from lib.promote import cmd_promote_check
    from lib.search import cmd_search
    from lib.seal import cmd_sync_rules
    from lib.session import cmd_meta, cmd_session_start, cmd_sync_resume
    from lib.storage import cmd_commit_daily, cmd_init, cmd_note, cmd_pending, cmd_redact, cmd_restore, cmd_snapshot
    from lib.todo import cmd_todo
    from lib.transcript import cmd_transcript
    from lib.mailbox import cmd_mailbox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mem.py",
        description="ai-fish 跨会话记忆工具（原始事件、日记固化、检索、数据库、快照、校验）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="显示记忆库状态")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("init", help="初始化全新的记忆库目录结构与模板")
    p.add_argument("--dir", default="", help="初始化目标目录（默认当前记忆库）")
    p.add_argument("--force", action="store_true", help="强制覆盖已存在的模板文件")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("session-start", help="会话启动：打印规则、长期记忆、最近日记和待处理事件")
    p.add_argument("--brief", action="store_true", help="只输出封印、pending、状态与元文档入口，不打印长期记忆全文")
    p.set_defaults(func=cmd_session_start)

    p = sub.add_parser("meta", help="打印 META.md 元文档（阅读入口/触发索引）")
    p.add_argument("--path", action="store_true", help="只输出 META.md 的绝对路径")
    p.set_defaults(func=cmd_meta)

    p = sub.add_parser("note", help="追加一条原始事件")
    p.add_argument("--kind", required=True, choices=KINDS)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--text", help="事件文本；用 - 从标准输入读取")
    g.add_argument("--file", help="从 UTF-8 文件读取事件文本")
    p.add_argument("--ref", default="", help="来源/证据引用，例如 evt-... 或文件路径")
    p.add_argument("--actor", default="agent", choices=("user", "agent", "system"))
    p.add_argument("--tag", action="append", default=[], help="可重复的标签")
    p.add_argument("--idempotent", action="store_true", help="若今日已存在相同 kind/text/ref/actor 则跳过追加，保持幂等")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("pending", help="列出尚未固化的原始事件")
    p.add_argument("--full", action="store_true", help="显示完整文本")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("transcript", help="只读查看 DSH 会话原始记录摘要（用于遗漏恢复）")
    p.add_argument("--session", default="current", help="current、previous 或 session-id 前缀")
    p.add_argument("--list", action="store_true", help="列出可用会话记录")
    p.add_argument("--include-tools", action="store_true", help="包含工具调用与结果")
    p.add_argument("--include-context", action="store_true", help="包含 runtime/goal/instruction 消息")
    p.add_argument("--max-chars", type=int, default=12000)
    p.add_argument("--max-item-chars", type=int, default=700)
    p.set_defaults(func=cmd_transcript)

    p = sub.add_parser("commit-daily", help="提交当日日记并登记已处理事件")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--file", required=True, help="日记草稿（UTF-8）")
    p.add_argument("--events", required=True, help="逗号分隔的事件编号")
    p.add_argument("--scene", help="本次归档的现场快照（短文本；长文本用 --scene-file）")
    p.add_argument("--scene-file", dest="scene_file", help="现场快照文件（UTF-8，≤1200 字）")
    p.set_defaults(func=cmd_commit_daily)

    p = sub.add_parser("search", help="检索长期记忆、日记和原始事件")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--scope", default="admin", choices=("admin", "public"), help="检索权限范围：admin（默认全量）或 public（仅公开记忆）")
    p.add_argument("--text-only", action="store_true", help="跳过数据库 FTS5，强制进行纯文本扫描")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("todo", help="汇总未完成待办（读日记各批次「待办」段，只读）")
    p.add_argument("--days", type=int, default=2, help="只看最近 N 天的日记，0 表示不限（默认 2）")
    p.add_argument("--all", action="store_true", help="扫描全部日记")
    p.add_argument("--rollover", action="store_true", help="只显示今天之前的未完成待办（跨天滚转，含天数标记）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--done", default="", help="把列出的第 N 条标为已办，逗号分隔，如 1,3")
    p.add_argument("--include-done", action="store_true", help="连已办的一起显示")
    p.add_argument("--max-chars", type=int, default=200, help="单条最大字符数")
    p.set_defaults(func=cmd_todo)

    p = sub.add_parser("snapshot", help="修改文件前建立不可覆盖快照")
    p.add_argument("--file", required=True, help="相对记忆库根目录的文件")
    p.add_argument("--note", default="", help="快照原因")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("restore", help="从快照恢复（需要 --yes）")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("redact", help="数据遗忘与墓碑遮蔽（按用户授权抹除敏感事件正文，保留行序与编号连续性）")
    p.add_argument("--event", required=True, help="要遮蔽的事件编号，例如 evt-20261102-120000-abcd")
    p.add_argument("--reason", default="用户明确要求删除", help="遮蔽原因（用于系统审计存证）")
    p.add_argument("--yes", action="store_true", help="确认不可逆执行墓碑遮蔽")
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser("sync-rules", help="从权威 RULES.md 修复工作区镜像")
    p.set_defaults(func=cmd_sync_rules)

    p = sub.add_parser("grant", help="记录、查询口头授权（解决审批链路断层）")
    p.add_argument("--topic", help="授权主题，如 '安装 ffmpeg'")
    p.add_argument("--ref", default="", help="证据引用，如 evt-...（用户当场同意的那条事件）")
    p.add_argument("--note", default="", help="备注说明")
    p.add_argument("--list", action="store_true", help="列出所有活跃授权")
    p.add_argument("--check", help="按关键词检查是否有匹配的活跃授权")
    p.add_argument("--revoke", help="撤销指定 ID 的授权")
    p.set_defaults(func=cmd_grant)

    p = sub.add_parser("sync-resume", help="未固化事件存在时刷新现场快照（防跨会话断层）")
    p.add_argument("--force", action="store_true", help="即使没有 pending 事件也强制刷新")
    p.set_defaults(func=cmd_sync_resume)

    p = sub.add_parser("promote-check", help="检测日记中尚未升格到长期记忆的候选项")
    p.add_argument("--days", type=int, default=3, help="扫描最近 N 天（默认 3）")
    p.add_argument("--json", action="store_true", help="同时输出 JSON 格式")
    p.set_defaults(func=cmd_promote_check)

    p = sub.add_parser("db", help="轻量级数据库管理（长期记忆结构化、FTS 索引、数据同步）")
    db_sub = p.add_subparsers(dest="db_action", required=True)

    sp = db_sub.add_parser("sync", help="从文本文件全量同步/重建 SQLite 数据库")
    sp.add_argument("--rebuild", action="store_true", help="清空并彻底重建数据库与索引")

    sp = db_sub.add_parser("status", help="查看数据库文件、表结构与同步状态")

    sp = db_sub.add_parser("get", help="按编号查询长期记忆结构化条目（如 U-009, F-001）")
    sp.add_argument("key", help="条目编号，例如 U-009, F-001, M-001")
    sp.add_argument("--scope", default="admin", choices=("admin", "public"), help="权限范围")

    sp = db_sub.add_parser("query", help="执行只读 SQL SELECT 语句")
    sp.add_argument("sql", help="SQL 查询语句 (SELECT ...)")

    sp = db_sub.add_parser("events", help="多条件筛选原始事件")
    sp.add_argument("--kind", choices=KINDS)
    sp.add_argument("--actor", choices=("user", "agent", "system"))
    sp.add_argument("--date", help="YYYY-MM-DD")
    sp.add_argument("--pending", action="store_true", help="只查未固化事件")
    sp.add_argument("--scope", default="admin", choices=("admin", "public"), help="权限范围")
    sp.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_db)

    p = sub.add_parser("mailbox", help="中央信箱管理（查看/回复跨会话与多智能体异步信件）")
    mb_sub = p.add_subparsers(dest="mailbox_action", help="信箱操作")
    sp = mb_sub.add_parser("list", help="查看信箱信件")
    sp.add_argument("--status", choices=("pending", "replied", "unreplied", "busy", "all"), default="all")
    sp.add_argument("--limit", type=int, default=10)
    sp = mb_sub.add_parser("reply", help="回复信箱信件")
    sp.add_argument("--id", dest="msg_id", required=True, help="信件编号")
    sp.add_argument("--text", required=True, help="回复正文")
    p.set_defaults(func=cmd_mailbox)

    p = sub.add_parser("audit", help="可追溯性与记忆卫生自检")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("verify", help="完整性自检")
    p.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except MemError as exc:
        print(f"ERROR: {exc}")
        return 1
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        print("INTERRUPTED")
        return 130
    except Exception as exc:  # noqa: BLE001 - surface unexpected failures
        print(f"ERROR: unexpected {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
