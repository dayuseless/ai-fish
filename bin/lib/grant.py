# -*- coding: utf-8 -*-
"""ai-fish oral approvals tracking (grants.jsonl)."""
from __future__ import annotations

import argparse
import secrets

from .core import (
    GRANTS_PATH,
    MemError,
    append_jsonl,
    ensure_dirs,
    iso,
    load_config,
    memory_lock,
    now,
    read_jsonl,
    session_id,
)
from .seal import require_seal


def cmd_grant(args: argparse.Namespace) -> int:
    """记录、查询或撤销口头授权。

    写路径：index/grants.jsonl（追加），走封印检查与写锁。
    读路径：--list / --check 不需要封印。
    用法示例：
        mem.py grant --topic "安装 ffmpeg" --ref "evt-20261031-xxx"
        mem.py grant --list
        mem.py grant --check "ffmpeg"
        mem.py grant --revoke grant-20261031-221300-ab12
    """
    ensure_dirs()

    if args.list:
        rows, errors = read_jsonl(GRANTS_PATH)
        if errors:
            for err in errors[:3]:
                print(f"WARN: grants.jsonl 损坏行：{err}")
        active: dict[str, dict] = {}
        for r in rows:
            gid = str(r.get("id", ""))
            if not gid:
                continue
            if r.get("revoked"):
                active.pop(gid, None)
            else:
                active[gid] = r
        revoked = len(rows) - len(active)
        print(f"GRANTS: {len(active)} active" + (f", {revoked} revoked/meta" if revoked else ""))
        for r in active.values():
            topic = r.get("topic", "?")
            ref = r.get("ref") or "-"
            at = r.get("at", "?")
            print(f"  [{r.get('id', '?')}] {topic}  ref={ref}  at={at}")
            if r.get("note"):
                print(f"    note: {r['note']}")
        if not active:
            print("  （无活跃授权）")
        return 0

    if args.check:
        rows, _ = read_jsonl(GRANTS_PATH)
        active: dict[str, dict] = {}
        for r in rows:
            gid = str(r.get("id", ""))
            if not gid:
                continue
            if r.get("revoked"):
                active.pop(gid, None)
            else:
                active[gid] = r
        query = args.check.casefold()
        matches = [
            r for r in active.values()
            if query in str(r.get("topic", "")).casefold()
        ]
        if matches:
            print(f"GRANT_FOUND: {len(matches)} matching grant(s)")
            for r in matches:
                print(f"  [{r.get('id')}] {r.get('topic')}  ref={r.get('ref') or '-'}")
            return 0
        print("GRANT_NOT_FOUND")
        return 0

    if args.revoke:
        rows, _ = read_jsonl(GRANTS_PATH)
        active: dict[str, dict] = {}
        for r in rows:
            gid = str(r.get("id", ""))
            if not gid:
                continue
            if r.get("revoked"):
                active.pop(gid, None)
            else:
                active[gid] = r
        if args.revoke not in active:
            raise MemError(f"找不到活跃授权：{args.revoke}")
        target = active[args.revoke]
        with memory_lock():
            append_jsonl(GRANTS_PATH, {
                "id": target["id"],
                "revoked": True,
                "revokedAt": iso(),
                "revokedBy": session_id(),
            })
        print(f"GRANT_REVOKED {target['id']} topic={target.get('topic')}")
        return 0

    if not args.topic:
        raise MemError("需要 --topic（授权主题）")

    cfg = load_config()
    require_seal(cfg)

    with memory_lock():
        gid = f"grant-{now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        entry = {
            "id": gid,
            "at": iso(),
            "topic": args.topic,
            "ref": args.ref or "",
            "note": args.note or "",
            "session": session_id(),
        }
        append_jsonl(GRANTS_PATH, entry)

    print(f"GRANT_OK {gid} topic={args.topic}")
    return 0
