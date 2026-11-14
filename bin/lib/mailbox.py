# -*- coding: utf-8 -*-
r"""ai-fish cross-session mailbox tool: inspect and reply to messages from Soli (QQ bridge).

Architecture role (方案 B - 用 / 中央信箱):
  - Soli posts messages to D:\qq-bridge\state\mailbox.db via qq_talk_to_admin.
  - The admin / main session in D:\记忆 can inspect pending or historic letters.
  - Can record replies directly into the mailbox.
  - Zero lock contention on memory.db; mailbox.db is an independent SQLite database.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

MAILBOX_DB_PATH = Path(r"D:\qq-bridge\state\mailbox.db")
BJ_TZ = timezone(timedelta(hours=8))


def _get_db() -> sqlite3.Connection:
    MAILBOX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(MAILBOX_DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("""
    CREATE TABLE IF NOT EXISTS mailbox (
      id TEXT PRIMARY KEY,
      sender TEXT NOT NULL,
      recipient TEXT NOT NULL,
      text TEXT NOT NULL,
      status TEXT NOT NULL,
      reply_text TEXT DEFAULT '',
      error TEXT DEFAULT '',
      created_at TEXT NOT NULL,
      replied_at TEXT DEFAULT '',
      archived INTEGER DEFAULT 0
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mb_recip ON mailbox(recipient, status);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mb_sender ON mailbox(sender, created_at);")
    return conn


def cmd_mailbox(args: argparse.Namespace) -> int:
    action = getattr(args, "mailbox_action", "list") or "list"

    if action == "list":
        conn = _get_db()
        clauses = []
        params = []

        if not getattr(args, "show_archived", False):
            clauses.append("archived = 0")

        status_filter = getattr(args, "status", "all")
        if status_filter and status_filter != "all":
            clauses.append("status = ?")
            params.append(status_filter)

        sender_filter = getattr(args, "sender", "")
        if sender_filter:
            clauses.append("sender = ?")
            params.append(sender_filter)

        recipient_filter = getattr(args, "recipient", "")
        if recipient_filter:
            clauses.append("recipient = ?")
            params.append(recipient_filter)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = getattr(args, "limit", 10) or 10
        params.append(limit)

        cur = conn.cursor()
        rows = cur.execute(f"""
        SELECT id, sender, recipient, text, status, reply_text, error, created_at, replied_at, archived
        FROM mailbox
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ?
        """, params).fetchall()

        print(f"===== 中央信箱 mailbox.db (展示最近 {len(rows)} 条) =====")
        if not rows:
            print("（信箱为空或无匹配信件）")
            return 0

        # Display chronologically
        for m in reversed(rows):
            mid = m["id"]
            sender = m["sender"]
            recipient = m["recipient"]
            st = m["status"]
            created = m["created_at"]
            text = m["text"]
            reply = m["reply_text"]
            err = m["error"]

            st_icon = "⏳" if st == "pending" else ("✅" if st == "replied" else ("🚫" if st == "busy" else "✉️"))
            print(f"{st_icon} [{st.upper()}] 编号: {mid} | 时间: {created}")
            print(f"   发信人: {sender} -> 收信人: {recipient}")
            print(f"   正文: {text}")
            if reply:
                print(f"   回复: {reply} (回复时间: {m['replied_at']})")
            if err:
                print(f"   状态备注: {err}")
            print("-" * 50)
        return 0

    elif action == "reply":
        msg_id = getattr(args, "msg_id", "").strip()
        reply_text = getattr(args, "text", "").strip()
        if not msg_id or not reply_text:
            print("[ERR] 回复信件需要提供 --id <信件编号> 和 --text <回复文本>")
            return 1

        conn = _get_db()
        cur = conn.cursor()
        hit = cur.execute("SELECT * FROM mailbox WHERE id = ?", (msg_id,)).fetchone()
        if not hit:
            print(f"[ERR] 未找到编号为 {msg_id} 的信件")
            return 1

        now_iso = datetime.now(BJ_TZ).isoformat()
        cur.execute("""
        UPDATE mailbox
        SET status = 'replied', reply_text = ?, replied_at = ?
        WHERE id = ?
        """, (reply_text, now_iso, msg_id))
        conn.commit()

        print(f"[OK] 已成功回复信件 {msg_id}:")
        print(f"     原信: {hit['text']}")
        print(f"     回复: {reply_text}")
        return 0

    elif action == "archive":
        days = getattr(args, "days", 7) or 7
        conn = _get_db()
        cur = conn.cursor()
        cutoff = (datetime.now(BJ_TZ) - timedelta(days=days)).isoformat()
        cur.execute("""
        UPDATE mailbox
        SET archived = 1
        WHERE created_at < ? AND (status = 'replied' OR status = 'unreplied' OR status = 'expired')
        """, (cutoff,))
        conn.commit()
        print(f"[OK] 已归档 {cur.rowcount} 条超过 {days} 天的历史信件。")
        return 0

    else:
        print(f"[ERR] 未知动作: {action}")
        return 1
