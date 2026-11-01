# -*- coding: utf-8 -*-
"""ai-fish lightweight sqlite database for long-term memory maintenance and fast indexing.

Roles:
  - Canonical ground truth remains plain text (daily/raw/*.jsonl, daily/*.md, long-term *.md).
  - SQLite (index/memory.db) provides a fast, structured, derived query engine & full-text search.
  - Zero third-party dependencies (standard library sqlite3).
  - 100% disposable and rebuildable from plain-text files anytime.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from .core import (
    BASE,
    DAILY,
    INDEX,
    RAW,
    MemError,
    iso,
    read_text,
    rel_posix,
)
from .storage import all_raw_events, processed_ids

DB_NAME = "memory.db"


def get_db_path(base: Path | None = None) -> Path:
    target_base = base or BASE
    return target_base / "index" / DB_NAME


def cjk_tokenize(text: str) -> str:
    """Inserts spaces around CJK characters to enable phrase matching in SQLite unicode61."""
    if not text:
        return ""
    # Unicode CJK Unified Ideographs block
    return re.sub(r"([\u4e00-\u9fff])", r" \1 ", text)


def build_fts_query(query_str: str) -> str:
    """Converts a user search query into SQLite FTS5 phrase and token matches."""
    terms = query_str.strip().split()
    if not terms:
        return ""
    clauses: list[str] = []
    for term in terms:
        # Tokenize CJK chars while preserving ascii sequences
        tok_parts = cjk_tokenize(term).split()
        if not tok_parts:
            continue
        cleaned = " ".join(p.replace('"', '""') for p in tok_parts)
        clauses.append(f'"{cleaned}"')
    return " AND ".join(clauses)


def get_db(base: Path | None = None, write: bool = False) -> sqlite3.Connection:
    db_path = get_db_path(base)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    if write:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection, drop_existing: bool = False) -> None:
    cur = conn.cursor()
    if drop_existing:
        cur.executescript("""
        DROP TABLE IF EXISTS fts_memory;
        DROP TABLE IF EXISTS long_term_items;
        DROP TABLE IF EXISTS raw_events;
        DROP TABLE IF EXISTS daily_logs;
        DROP TABLE IF EXISTS db_meta;
        """)

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS db_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS long_term_items (
        id TEXT PRIMARY KEY,
        item_key TEXT NOT NULL,
        doc TEXT NOT NULL,
        section TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        evidence TEXT DEFAULT '',
        doc_version TEXT DEFAULT '',
        visibility TEXT DEFAULT 'admin_only',
        synced_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_lt_doc ON long_term_items(doc);
    CREATE INDEX IF NOT EXISTS idx_lt_key ON long_term_items(item_key);
    CREATE INDEX IF NOT EXISTS idx_lt_vis ON long_term_items(visibility);

    CREATE TABLE IF NOT EXISTS raw_events (
        id TEXT PRIMARY KEY,
        ts TEXT NOT NULL,
        date TEXT NOT NULL,
        kind TEXT NOT NULL,
        actor TEXT NOT NULL,
        text TEXT NOT NULL,
        ref TEXT DEFAULT '',
        tags TEXT DEFAULT '',
        is_pending INTEGER DEFAULT 0,
        visibility TEXT DEFAULT 'admin_only'
    );

    CREATE INDEX IF NOT EXISTS idx_raw_date ON raw_events(date);
    CREATE INDEX IF NOT EXISTS idx_raw_kind ON raw_events(kind);
    CREATE INDEX IF NOT EXISTS idx_raw_actor ON raw_events(actor);
    CREATE INDEX IF NOT EXISTS idx_raw_pending ON raw_events(is_pending);
    CREATE INDEX IF NOT EXISTS idx_raw_vis ON raw_events(visibility);

    CREATE TABLE IF NOT EXISTS daily_logs (
        date TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        batch_count INTEGER DEFAULT 0,
        char_count INTEGER DEFAULT 0,
        summary TEXT DEFAULT '',
        content TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory USING fts5(
        category UNINDEXED,
        doc UNINDEXED,
        item_id,
        title,
        body,
        tags,
        tokenize='unicode61'
    );
    """)
    conn.commit()


def parse_markdown_items(doc_name: str, text: str) -> list[dict[str, str]]:
    """Extracts structured items from Markdown long-term files."""
    lines = text.splitlines()
    version = ""
    m_ver = re.search(r"版本[：:]\s*([0-9\.]+)", text)
    if m_ver:
        version = m_ver.group(1)

    items: list[dict[str, str]] = []
    current_sec = "顶层"
    current_item: dict[str, str] | None = None

    bold_item_re = re.compile(r"^\s*-\s+\*\*([^*]+?)\*\*[：:]\s*(.*)$")
    plain_item_re = re.compile(r"^\s*-\s+([^：:\n]{2,30})[：:]\s*(.*)$")
    sub_re = re.compile(r"^\s{2,}-\s+(.*)$")
    sec_re = re.compile(r"^#{1,4}\s+(.*)$")

    item_idx = 0
    for line in lines:
        sm = sec_re.match(line)
        if sm:
            if current_item:
                items.append(current_item)
                current_item = None
            current_sec = sm.group(1).strip()
            continue

        im = bold_item_re.match(line)
        if im:
            if current_item:
                items.append(current_item)
            header = im.group(1).strip()
            rest = im.group(2).strip()
            if "｜" in header:
                k, t = header.split("｜", 1)
            elif "|" in header:
                k, t = header.split("|", 1)
            else:
                k, t = header, ""
            item_idx += 1
            key_clean = k.strip() or f"item_{item_idx}"
            current_item = {
                "id": f"{doc_name}:{key_clean}",
                "doc": doc_name,
                "section": current_sec,
                "key": key_clean,
                "title": t.strip(),
                "content": rest,
                "evidence": "",
                "version": version,
            }
            continue

        pm = plain_item_re.match(line)
        if pm and line.strip().startswith("- "):
            if current_item:
                items.append(current_item)
            header = pm.group(1).strip()
            rest = pm.group(2).strip()
            item_idx += 1
            current_item = {
                "id": f"{doc_name}:{header or f'item_{item_idx}'}",
                "doc": doc_name,
                "section": current_sec,
                "key": header,
                "title": "",
                "content": rest,
                "evidence": "",
                "version": version,
            }
            continue

        sub = sub_re.match(line)
        if sub and current_item:
            stext = sub.group(1).strip()
            if any(stext.startswith(prefix) for prefix in ("证据", "来源", "说明", "边界", "注意", "推论")):
                if current_item["evidence"]:
                    current_item["evidence"] += "；" + stext
                else:
                    current_item["evidence"] = stext
            else:
                current_item["content"] += "\n" + stext
            continue

        if current_item and line.startswith(("    ", "\t")):
            current_item["content"] += "\n" + line.strip()

    if current_item:
        items.append(current_item)

    # De-duplicate IDs within same document
    id_counts: dict[str, int] = {}
    for it in items:
        base_id = it["id"]
        cnt = id_counts.get(base_id, 0)
        id_counts[base_id] = cnt + 1
        if cnt > 0:
            it["id"] = f"{base_id}_{cnt}"

    return items


def sync_all(base: Path | None = None, rebuild: bool = False) -> dict[str, Any]:
    """Synchronizes plain text long-term docs, raw events, and daily logs into SQLite."""
    t0 = time.perf_counter()
    target_base = base or BASE
    conn = get_db(target_base, write=True)
    init_db(conn, drop_existing=rebuild)

    cur = conn.cursor()

    if rebuild:
        cur.execute("DELETE FROM fts_memory;")
        cur.execute("DELETE FROM long_term_items;")
        cur.execute("DELETE FROM raw_events;")
        cur.execute("DELETE FROM daily_logs;")

    # 1. Sync long-term documents
    long_term_docs = ["SELF.md", "USER.md", "MEMORY.md", "RULES.md", "SPEC.md"]
    lt_count = 0
    now_str = iso()

    # Clear previous long-term entries if incremental to prevent stale items
    cur.execute("DELETE FROM long_term_items;")
    cur.execute("DELETE FROM fts_memory WHERE category = 'long_term';")

    for doc_name in long_term_docs:
        doc_path = target_base / doc_name
        if not doc_path.is_file():
            continue
        try:
            content = read_text(doc_path)
        except Exception:
            continue
        items = parse_markdown_items(doc_name, content)
        for it in items:
            is_pub = "public" if (
                it["doc"] == "RULES.md"
                or it["key"].startswith(("U-010", "U-011", "F-001"))
                or any(w in it["title"] or w in it["section"] for w in ("授权", "规则", "公开", "设定", "人设", "自我认识", "运行环境"))
                or any(w in it["content"] for w in ("权限", "授权", "公开", "public", "rules"))
            ) else "admin_only"

            cur.execute("""
            INSERT OR REPLACE INTO long_term_items
            (id, item_key, doc, section, title, content, evidence, doc_version, visibility, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (it["id"], it["key"], it["doc"], it["section"], it["title"], it["content"], it["evidence"], it["version"], is_pub, now_str))

            # FTS index
            cur.execute("""
            INSERT INTO fts_memory (category, doc, item_id, title, body, tags)
            VALUES ('long_term', ?, ?, ?, ?, ?)
            """, (
                it["doc"],
                cjk_tokenize(it["key"]),
                cjk_tokenize(it["title"]),
                cjk_tokenize(it["content"]),
                cjk_tokenize(f"{it['section']} {it['evidence']}"),
            ))
            lt_count += 1

    # 2. Sync raw events
    events, _ = all_raw_events()
    done_ids = processed_ids()
    cur.execute("DELETE FROM raw_events;")
    cur.execute("DELETE FROM fts_memory WHERE category = 'raw_event';")

    raw_count = 0
    for path, _, obj in events:
        eid = obj.get("id")
        if not eid:
            continue
        ts = obj.get("ts", "")
        kind = obj.get("kind", "")
        actor = obj.get("actor", "")
        text = obj.get("text", "")
        ref = obj.get("ref", "")
        tags_list = obj.get("tags", [])
        tags_str = " ".join(tags_list) if isinstance(tags_list, list) else str(tags_list)
        is_pending = 0 if eid in done_ids else 1
        date_str = eid[4:12]
        if len(date_str) == 8:
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            date_str = path.stem

        is_pub = "public" if (
            obj.get("visibility") == "public"
            or any(t in tags_str.lower() for t in ("public", "grant", "rules", "cross-session", "system", "general"))
            or any(w in text for w in ("授权", "规则", "公开", "public", "system"))
        ) else "admin_only"

        cur.execute("""
        INSERT OR REPLACE INTO raw_events
        (id, ts, date, kind, actor, text, ref, tags, is_pending, visibility)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (eid, ts, date_str, kind, actor, text, ref, tags_str, is_pending, is_pub))

        rel_doc = rel_posix(path)
        cur.execute("""
        INSERT INTO fts_memory (category, doc, item_id, title, body, tags)
        VALUES ('raw_event', ?, ?, ?, ?, ?)
        """, (
            rel_doc,
            cjk_tokenize(eid),
            cjk_tokenize(f"[{kind}] {actor}"),
            cjk_tokenize(text),
            cjk_tokenize(f"{ref} {tags_str}"),
        ))
        raw_count += 1

    # 3. Sync daily logs
    cur.execute("DELETE FROM daily_logs;")
    cur.execute("DELETE FROM fts_memory WHERE category = 'daily_log';")
    daily_count = 0
    daily_dir = target_base / "daily"
    if daily_dir.is_dir():
        for df in sorted(daily_dir.glob("20??-??-??.md")):
            try:
                d_text = read_text(df)
            except Exception:
                continue
            d_date = df.stem
            b_count = d_text.count("## 批次")
            rel_df = rel_posix(df)
            cur.execute("""
            INSERT OR REPLACE INTO daily_logs
            (date, path, batch_count, char_count, summary, content, updated_at)
            VALUES (?, ?, ?, ?, '', ?, ?)
            """, (d_date, rel_df, b_count, len(d_text), d_text, now_str))

            cur.execute("""
            INSERT INTO fts_memory (category, doc, item_id, title, body, tags)
            VALUES ('daily_log', ?, ?, ?, ?, ?)
            """, (
                rel_df,
                cjk_tokenize(d_date),
                cjk_tokenize(f"Daily {d_date}"),
                cjk_tokenize(d_text),
                cjk_tokenize(d_date),
            ))
            daily_count += 1

    # Record sync metadata
    cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('last_sync_at', ?)", (now_str,))
    cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('long_term_count', ?)", (str(lt_count),))
    cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('raw_event_count', ?)", (str(raw_count),))
    cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('daily_count', ?)", (str(daily_count),))
    cur.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('schema_version', '1')")

    conn.commit()
    conn.close()

    duration_ms = (time.perf_counter() - t0) * 1000
    return {
        "long_term": lt_count,
        "raw_events": raw_count,
        "dailies": daily_count,
        "duration_ms": duration_ms,
    }


def search_fts(query: str, limit: int = 50, category: str | None = None, base: Path | None = None) -> list[dict[str, Any]]:
    """Executes high-speed ranked FTS search across memory store."""
    db_path = get_db_path(base)
    if not db_path.is_file():
        return []

    fts_q = build_fts_query(query)
    if not fts_q:
        return []

    conn = get_db(base)
    try:
        sql = """
        SELECT category, doc, item_id, title, body, tags, rank
        FROM fts_memory
        WHERE fts_memory MATCH ?
        """
        params: list[Any] = [fts_q]
        if category:
            sql += " AND category = ?"
            params.append(category)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            # Strip artificial spaces inserted for CJK
            results.append({
                "category": r["category"],
                "doc": r["doc"],
                "item_id": r["item_id"].replace(" ", ""),
                "title": r["title"].replace(" ", ""),
                "body": r["body"].replace(" ", ""),
                "tags": r["tags"].replace(" ", ""),
                "rank": r["rank"],
            })
        return results
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def get_long_term_item(item_key: str, base: Path | None = None) -> dict[str, Any] | None:
    db_path = get_db_path(base)
    if not db_path.is_file():
        return None
    conn = get_db(base)
    try:
        cur = conn.execute("""
        SELECT id, item_key, doc, section, title, content, evidence, doc_version, synced_at
        FROM long_term_items
        WHERE item_key = ? OR id = ?
        LIMIT 1
        """, (item_key, item_key))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def query_raw_events(
    kind: str | None = None,
    actor: str | None = None,
    date: str | None = None,
    is_pending: bool | None = None,
    limit: int = 50,
    base: Path | None = None,
) -> list[dict[str, Any]]:
    db_path = get_db_path(base)
    if not db_path.is_file():
        return []
    conn = get_db(base)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if actor:
            clauses.append("actor = ?")
            params.append(actor)
        if date:
            clauses.append("date = ?")
            params.append(date)
        if is_pending is not None:
            clauses.append("is_pending = ?")
            params.append(1 if is_pending else 0)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT id, ts, date, kind, actor, text, ref, tags, is_pending FROM raw_events{where} ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def db_status_info(base: Path | None = None) -> dict[str, Any]:
    db_path = get_db_path(base)
    if not db_path.is_file():
        return {"exists": False, "path": str(db_path)}

    conn = get_db(base)
    try:
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        meta_rows = conn.execute("SELECT key, value FROM db_meta;").fetchall()
        meta = {r["key"]: r["value"] for r in meta_rows}
        lt_c = conn.execute("SELECT count(*) FROM long_term_items;").fetchone()[0]
        ev_c = conn.execute("SELECT count(*) FROM raw_events;").fetchone()[0]
        pending_c = conn.execute("SELECT count(*) FROM raw_events WHERE is_pending = 1;").fetchone()[0]
        dl_c = conn.execute("SELECT count(*) FROM daily_logs;").fetchone()[0]
        fts_c = conn.execute("SELECT count(*) FROM fts_memory;").fetchone()[0]
        latest_event = conn.execute("SELECT max(ts) FROM raw_events;").fetchone()[0]

        return {
            "exists": True,
            "path": str(db_path),
            "size_bytes": db_path.stat().st_size,
            "sqlite_version": sqlite3.sqlite_version,
            "integrity": integrity,
            "meta": meta,
            "latest_event": latest_event,
            "counts": {
                "long_term_items": lt_c,
                "raw_events": ev_c,
                "pending_events": pending_c,
                "daily_logs": dl_c,
                "fts_indexed": fts_c,
            },
        }
    finally:
        conn.close()


def cmd_db(args: argparse.Namespace) -> int:
    action = getattr(args, "db_action", None)
    if not action:
        print("请指定 db 子命令：sync, status, get, query, events")
        return 1

    if action == "sync":
        rebuild = getattr(args, "rebuild", False)
        print(f"正在同步文本记忆到轻量级数据库 (rebuild={rebuild})...")
        res = sync_all(rebuild=rebuild)
        print(f"DB_SYNC_OK: 耗时 {res['duration_ms']:.1f}ms")
        print(f"  长期记忆条目: {res['long_term']}")
        print(f"  原始事件记录: {res['raw_events']}")
        print(f"  日记归档记录: {res['dailies']}")
        return 0

    if action == "status":
        info = db_status_info()
        print("===== AI-FISH DB STATUS =====")
        if not info["exists"]:
            print(f"数据库未就绪 (文件不存在: {info['path']})")
            print("提示: 可运行 `mem.py db sync` 初始化部署数据库。")
            return 0
        print(f"数据库路径 : {info['path']}")
        print(f"数据库大小 : {info['size_bytes'] / 1024:.1f} KiB")
        print(f"SQLite版本 : {info['sqlite_version']}")
        print(f"完整性校验 : {info['integrity']}")
        meta = info.get("meta", {})
        print(f"最后同步时间: {meta.get('last_sync_at', '未知')}")
        counts = info.get("counts", {})
        print(f"长期记忆条目: {counts.get('long_term_items', 0)}")
        print(f"原始事件记录: {counts.get('raw_events', 0)} (待固化: {counts.get('pending_events', 0)})")
        print(f"日记日志条数: {counts.get('daily_logs', 0)}")
        print(f"全文索引记录: {counts.get('fts_indexed', 0)}")
        print(f"最后同步时间: {meta.get('last_sync_at', '未知')}")
        if info.get("latest_event"):
            print(f"最新事件时间: {info['latest_event']}")
        return 0

    if action == "get":
        item_key = args.key.strip()
        item = get_long_term_item(item_key)
        if not item:
            print(f"未在长期记忆数据库中找到条目: {item_key}")
            return 1
        print(f"[{item['item_key']}] {item['title']}")
        print(f"来源文档 : {item['doc']} (v{item['doc_version']}) | 章节: {item['section']}")
        print(f"内容正文 :\n{item['content']}")
        if item.get("evidence"):
            print(f"支撑证据 : {item['evidence']}")
        return 0

    if action == "query":
        sql = args.sql.strip()
        # Safety guard: read-only SELECT queries only
        if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            raise MemError("出于安全性，db query 仅允许只读 SELECT 语句")
        conn = get_db()
        try:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            if not rows:
                print("查询结果为空。")
                return 0
            cols = [d[0] for d in cur.description]
            print(f"Query Result ({len(rows)} rows):")
            for r in rows:
                row_dict = {col: r[col] for col in cols}
                print(row_dict)
            return 0
        finally:
            conn.close()

    if action == "events":
        evs = query_raw_events(
            kind=getattr(args, "kind", None),
            actor=getattr(args, "actor", None),
            date=getattr(args, "date", None),
            is_pending=True if getattr(args, "pending", False) else None,
            limit=getattr(args, "limit", 50),
        )
        print(f"RAW_EVENTS ({len(evs)} 条匹配):")
        for e in evs:
            status_tag = "[PENDING]" if e["is_pending"] else "[SOLIDIFIED]"
            print(f"  {status_tag} [{e['id']}] {e['ts']} [{e['kind']}] {e['actor']}: {e['text'][:100]}")
        return 0

    print(f"未知 action: {action}")
    return 1
