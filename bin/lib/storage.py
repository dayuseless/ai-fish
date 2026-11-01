# -*- coding: utf-8 -*-
"""ai-fish storage: raw events, commit-daily, snapshots, and restores."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

from .core import (
    BASE,
    DAILY,
    EVENTS_INDEX,
    INDEX,
    MANIFEST_PATH,
    PROCESSED_PATH,
    RAW,
    REQUIRED_SECTIONS,
    RESUME_MAX_CHARS,
    RESUME_PATH,
    SNAPSHOTS,
    MemError,
    append_jsonl,
    atomic_write,
    atomic_write_bytes,
    count_lines,
    ensure_dirs,
    is_under,
    iso,
    load_config,
    load_state,
    memory_lock,
    now,
    read_jsonl,
    read_text,
    rel_posix,
    save_state,
    session_id,
    sha256_file,
)
from .seal import require_seal


def processed_ids() -> set[str]:
    rows, errors = read_jsonl(PROCESSED_PATH)
    if errors:
        for err in errors:
            print(f"WARN: processed.jsonl 损坏行：{err}")
    return {str(r["id"]) for r in rows if r.get("id")}


def all_raw_events():
    """Return ([(path, lineno, obj)], parse_errors) for all raw events."""
    events: list[tuple[Path, int, dict]] = []
    errors: list[str] = []
    if not RAW.exists():
        return events, errors
    for path in sorted(RAW.glob("*.jsonl")):
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"{rel_posix(path)}:{lineno}: {exc}")
                    continue
                if not isinstance(obj, dict):
                    errors.append(f"{rel_posix(path)}:{lineno}: 不是 JSON 对象")
                    continue
                events.append((path, lineno, obj))
    return events, errors


def event_map() -> dict[str, tuple[Path, int, dict]]:
    events, _ = all_raw_events()
    out = {}
    for path, lineno, obj in events:
        eid = obj.get("id")
        if eid and eid not in out:
            out[eid] = (path, lineno, obj)
    return out


def pending_events(report_errors: bool = False, error_stream=None) -> list[tuple[Path, int, dict]]:
    events, errors = all_raw_events()
    if errors and report_errors:
        stream = error_stream or sys.stdout
        print(f"WARN: 原始事件解析错误 {len(errors)} 条；运行 `mem.py verify` 查看详情。", file=stream)
        for err in errors[:3]:
            print(f"  {err}", file=stream)
    done = processed_ids()
    out = [item for item in events if item[2].get("id") not in done]
    out.sort(key=lambda item: (item[2].get("ts") or "", item[1]))
    return out


def cmd_note(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    require_seal(cfg)

    if args.text is not None and args.file is not None:
        raise MemError("--text 与 --file 只能二选一")
    if args.text == "-":
        text = sys.stdin.read()
    elif args.file is not None:
        text = read_text(Path(args.file))
    elif args.text is not None:
        text = args.text
    else:
        raise MemError("需要 --text 或 --file")

    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise MemError("事件文本为空")
    limit = int(cfg.get("max_note_chars", 12000))
    if len(text) > limit:
        raise MemError(f"事件文本过长（{len(text)} > {limit} 字符）；请拆分或精简")

    with memory_lock():
        return _write_note(args, text)


def _write_note(args: argparse.Namespace, text: str) -> int:
    ts = iso()
    date = ts[:10]
    eid = f"evt-{now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    raw_path = RAW / f"{date}.jsonl"
    line_no = count_lines(raw_path) + 1
    ref = args.ref or ""
    tags = list(args.tag or [])
    event = {
        "id": eid,
        "ts": ts,
        "date": date,
        "kind": args.kind,
        "actor": args.actor,
        "text": text,
        "ref": ref,
        "tags": tags,
        "source": f"session:{session_id()}",
        "recordedAt": ts,
    }
    append_jsonl(raw_path, event)
    try:
        append_jsonl(
            EVENTS_INDEX,
            {
                "id": eid,
                "ts": ts,
                "date": date,
                "kind": args.kind,
                "file": rel_posix(raw_path),
                "line": line_no,
                "preview": text[:160].replace("\n", " "),
                "ref": ref,
            },
        )
    except OSError as exc:
        print(f"WARN: 原始事件已写入，但索引写入失败（可由 verify 发现）：{exc}")
    try:
        state = load_state()
        state["lastNoteAt"] = ts
        save_state(state)
    except MemError as exc:
        print(f"WARN: 事件已写入，但 state 更新失败：{exc}")
    try:
        from .db import cjk_tokenize, get_db, get_db_path
        if get_db_path().is_file():
            conn = get_db(write=True)
            tags_str = " ".join(tags)
            conn.execute("""
            INSERT OR REPLACE INTO raw_events
            (id, ts, date, kind, actor, text, ref, tags, is_pending)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (eid, ts, date, args.kind, args.actor, text, ref, tags_str))
            conn.execute("""
            INSERT INTO fts_memory (category, doc, item_id, title, body, tags)
            VALUES ('raw_event', ?, ?, ?, ?, ?)
            """, (
                rel_posix(raw_path),
                cjk_tokenize(eid),
                cjk_tokenize(f"[{args.kind}] {args.actor}"),
                cjk_tokenize(text),
                cjk_tokenize(f"{ref} {tags_str}"),
            ))
            conn.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('raw_event_count', (SELECT count(*) FROM raw_events));")
            conn.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('last_note_at', ?);", (ts,))
            conn.commit()
            conn.close()
    except Exception:
        pass
    print(f"NOTE_OK {eid} {rel_posix(raw_path)}:{line_no}")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    ensure_dirs()
    pending = pending_events(
        report_errors=True,
        error_stream=(sys.stderr if args.json else None),
    )
    if args.json:
        print(json.dumps([obj for _, _, obj in pending], ensure_ascii=False, indent=2))
        return 0
    print(f"PENDING {len(pending)}")
    for path, lineno, obj in pending:
        print(f"[{obj.get('id')}] {obj.get('ts')} kind={obj.get('kind')} ref={obj.get('ref') or '-'}")
        if args.full:
            print(str(obj.get("text", "")))
            print()
        else:
            print(str(obj.get("text", "")).replace("\n", " ")[:200])
            print()
    return 0


def _load_resume_scene(args: argparse.Namespace) -> str | None:
    """读本次归档要写的「现场快照」；没给就返回 None（保留旧现场并告警）。"""
    inline = getattr(args, "scene", None)
    file_arg = getattr(args, "scene_file", None)
    if inline and file_arg:
        raise MemError("--scene 与 --scene-file 只能给一个")
    text = None
    if inline:
        text = inline
    elif file_arg:
        path = Path(file_arg)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_file():
            raise MemError(f"现场快照文件不存在：{path}")
        text = read_text(path)
    if text is None:
        return None
    text = text.replace("\r\n", "\n").strip()
    if len(text) < 10:
        raise MemError("现场快照太短（至少 10 字）：写清楚这段在做什么、下一步做什么")
    if len(text) > RESUME_MAX_CHARS:
        raise MemError(
            f"现场快照 {len(text)} 字，超过上限 {RESUME_MAX_CHARS}；"
            "它是给下个会话快速启动用的，请精简"
        )
    return text


def cmd_commit_daily(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    require_seal(cfg)

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as exc:
        raise MemError(f"--date 必须是 YYYY-MM-DD：{exc}") from exc

    draft = Path(args.file)
    if not draft.is_absolute():
        draft = Path.cwd() / draft
    if not draft.is_file():
        raise MemError(f"草稿文件不存在：{draft}")
    body = read_text(draft).replace("\r\n", "\n").strip()
    if not body:
        raise MemError("草稿为空")

    lines = {line.strip() for line in body.splitlines()}
    missing = [s for s in REQUIRED_SECTIONS if s not in lines]
    if missing:
        raise MemError("日记缺少必需章节：" + "、".join(missing))

    ids = [x for x in re.split(r"[,\s]+", args.events.strip()) if x]
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise MemError("--events 至少需要一个事件编号")

    emap = event_map()
    unknown = [eid for eid in ids if eid not in emap]
    if unknown:
        raise MemError("未知事件编号：" + ", ".join(unknown))
    for eid in ids:
        if emap[eid][2].get("date") != args.date:
            raise MemError(f"事件 {eid} 的日期是 {emap[eid][2].get('date')}，与 --date {args.date} 不符")

    scene = _load_resume_scene(args)
    with memory_lock():
        return _commit_daily_locked(args, body, ids, emap, scene)


def _commit_daily_locked(
    args: argparse.Namespace, body: str, ids: list[str], emap: dict, scene: str | None = None
) -> int:
    done = processed_ids()
    target = DAILY / f"{args.date}.md"
    existing = read_text(target) if target.exists() else ""
    already_in_daily = [eid for eid in ids if eid not in done and eid in existing]
    new_ids = [eid for eid in ids if eid not in done and eid not in already_in_daily]
    to_mark = [eid for eid in ids if eid not in done]

    if not to_mark:
        print("NO_NEW_EVENTS: 这些事件已经固化，无需写入。")
        return 0

    batch_ts = iso()
    if new_ids:
        if target.exists():
            snapshot_file(rel_posix(target), f"commit-daily 前快照 {args.date}")
        entry = (
            f"\n\n---\n\n## 固化批次 {batch_ts}\n\n"
            f"**原始事件**：{', '.join(new_ids)}\n\n"
            f"{body}\n"
        )
        if existing:
            content = existing.rstrip() + entry
        else:
            header = (
                f"# {args.date} 日记\n\n"
                f"> 摘要由智能体在固化时生成；事实以 `daily/raw/{args.date}.jsonl` 中的原始事件为准。\n"
            )
            content = header + entry
        atomic_write(target, content)
        written = read_text(target)
        if body.strip() not in written:
            raise MemError("日记写入后校验失败：正文未找到")

    for eid in to_mark:
        append_jsonl(
            PROCESSED_PATH,
            {
                "id": eid,
                "date": args.date,
                "daily": rel_posix(target),
                "at": batch_ts,
            },
        )

    try:
        from .db import get_db, get_db_path, sync_all
        if get_db_path().is_file():
            sync_all()
    except Exception:
        pass

    resume_written = False
    resume_error = None
    if scene:
        event_line = ", ".join(to_mark)
        if len(to_mark) > 3:
            event_line = f"{len(to_mark)} 条（{', '.join(to_mark[:2])} …）"
        resume_text = (
            "# 现场快照（归档时生成，覆盖写；供下个会话启动）\n\n"
            f"- 归档时间：{batch_ts}\n"
            f"- 对应日记：{rel_posix(target)}\n"
            f"- 本批事件：{event_line}\n"
            "\n---\n\n"
            f"{scene}\n"
        )
        try:
            atomic_write(RESUME_PATH, resume_text)
            resume_written = True
        except OSError as exc:
            resume_error = exc

    try:
        state = load_state()
        state["lastConsolidation"] = {
            "date": args.date,
            "at": batch_ts,
            "events": to_mark,
            "file": rel_posix(target),
        }
        if resume_written:
            state["resumeScene"] = {
                "at": batch_ts,
                "date": args.date,
                "file": rel_posix(RESUME_PATH),
                "chars": len(scene),
            }
        save_state(state)
    except MemError as exc:
        print(f"WARN: 日记与 processed 已写入，但 state 更新失败：{exc}")

    print(
        f"COMMIT_OK date={args.date} new_events={len(new_ids)} "
        f"marked={len(to_mark)} file={rel_posix(target)}"
    )
    if resume_written:
        print(f"RESUME_OK {rel_posix(RESUME_PATH)} chars={len(scene)}")
    elif resume_error is not None:
        print(f"WARN: 现场快照写入失败（{resume_error}）；日记已提交，可稍后重试")
    else:
        print("WARN: 本次没有提供 --scene/--scene-file，现场快照未更新（下次启动仍看到旧现场）")
    if already_in_daily:
        print("RECOVERED: 之前已写入日记但未登记的事件：" + ", ".join(already_in_daily))
    return 0


def snapshot_file(target_rel: str, note: str) -> Path:
    target = (BASE / target_rel).resolve() if not Path(target_rel).is_absolute() else Path(target_rel).resolve()
    if not is_under(target, BASE):
        raise MemError(f"快照目标不在记忆库内：{target}")
    if is_under(target, SNAPSHOTS):
        raise MemError("不能把 snapshots 目录内的文件作为快照目标")
    if not target.is_file():
        raise MemError(f"快照目标不存在：{target}")

    digest = sha256_file(target)
    stamp = now()
    dest_dir = SNAPSHOTS / stamp.strftime("%Y-%m-%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{target.name}.{stamp.strftime('%H%M%S')}.{digest[:8]}.bak"
    dest = dest_dir / base_name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{target.name}.{stamp.strftime('%H%M%S')}.{digest[:8]}.{counter}.bak"
        counter += 1
    shutil.copy2(target, dest)
    if sha256_file(dest) != digest:
        raise MemError(f"快照复制校验失败：{dest}")
    append_jsonl(
        MANIFEST_PATH,
        {
            "at": iso(),
            "target": rel_posix(target),
            "snapshot": rel_posix(dest),
            "sha256": digest,
            "bytes": dest.stat().st_size,
            "note": note,
        },
    )
    return dest


def cmd_snapshot(args: argparse.Namespace) -> int:
    ensure_dirs()
    with memory_lock():
        dest = snapshot_file(args.file, args.note or "")
        try:
            state = load_state()
            state["lastSnapshotAt"] = iso()
            save_state(state)
        except MemError as exc:
            print(f"WARN: 快照已写入，但 state 更新失败：{exc}")
        print(f"SNAPSHOT_OK {rel_posix(dest)}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    ensure_dirs()
    snap = Path(args.snapshot)
    if not snap.is_absolute():
        snap = BASE / snap
    snap = snap.resolve()
    if not is_under(snap, SNAPSHOTS):
        raise MemError("只允许从 snapshots/ 目录恢复")
    if not snap.is_file():
        raise MemError(f"快照不存在：{snap}")

    rows, errors = read_jsonl(MANIFEST_PATH)
    if errors:
        raise MemError("MANIFEST.jsonl 损坏：" + "; ".join(errors[:3]))
    entries = [r for r in rows if r.get("snapshot") == rel_posix(snap)]
    if not entries:
        raise MemError("该文件不在快照清单中，拒绝恢复")
    entry = entries[-1]
    expected = entry.get("sha256")
    actual = sha256_file(snap)
    if expected != actual:
        raise MemError(f"快照哈希不匹配：expected={expected} actual={actual}")

    target = (BASE / entry["target"]).resolve()
    if not is_under(target, BASE):
        raise MemError("快照目标不在记忆库内")

    if not args.yes:
        print("REFUSED: 恢复会覆盖当前文件；确认后加 --yes 再执行。")
        return 2

    with memory_lock():
        if target.exists():
            snapshot_file(rel_posix(target), "restore 前自动快照")
        atomic_write_bytes(target, snap.read_bytes())
        if target.name == "RULES.md":
            os.chmod(target, stat.S_IREAD)
        if sha256_file(target) != expected:
            raise MemError("恢复后哈希校验失败")
        append_jsonl(
            INDEX / "restores.jsonl",
            {"at": iso(), "snapshot": rel_posix(snap), "target": rel_posix(target), "sha256": expected},
        )
        print(f"RESTORE_OK {rel_posix(target)} <- {rel_posix(snap)}")
    return 0
