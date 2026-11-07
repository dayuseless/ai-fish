# -*- coding: utf-8 -*-
"""ai-fish status, integrity verification, and memory hygiene audit."""
from __future__ import annotations

import argparse
import re
import shutil
import stat
from collections import Counter
from pathlib import Path

from .core import (
    ARCHIVE,
    BASE,
    DAILY,
    EVENTS_INDEX,
    INDEX,
    LOCAL_SEAL,
    MANIFEST_PATH,
    PROCESSED_PATH,
    RAW,
    REQUIRED_SECTIONS,
    RULES_MIRROR,
    SNAPSHOTS,
    STATE_PATH,
    WORKSPACE,
    MemError,
    count_lines,
    ensure_dirs,
    iso,
    load_config,
    load_state,
    read_jsonl,
    read_text,
    rel_posix,
    sha256_file,
)
from .seal import check_seal, print_seal
from .storage import all_raw_events, event_map, processed_ids


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    info = check_seal(cfg)
    print("===== AI-FISH STATUS =====")
    print(f"time       : {iso()}")
    print(f"workspace  : {WORKSPACE}")
    print(f"memory root: {BASE}")
    print_seal(info)

    events, errors = all_raw_events()
    done = processed_ids()
    eids = [e[2].get("id") for e in events]
    counts = Counter(eids)
    dupes = sorted(eid for eid, count in counts.items() if eid and count > 1)
    pending = [e for e in events if e[2].get("id") not in done]
    print(f"raw events : {len(events)} (duplicates: {len(dupes)})")
    print(f"processed  : {len(done)}")
    print(f"pending    : {len(pending)}")
    print(f"parse errors: {len(errors)}")
    if pending:
        print("  pending ids: " + ", ".join(str(e[2].get("id")) for e in pending[:10]))
    dailies = sorted(DAILY.glob("20??-??-??.md"))
    print(f"daily logs : {len(dailies)}" + (f" (latest: {dailies[-1].name})" if dailies else ""))
    snaps = sorted(SNAPSHOTS.glob("**/*.bak"))
    print(f"snapshots  : {len(snaps)}")
    total = sum(p.stat().st_size for p in BASE.rglob("*") if p.is_file())
    print(f"size       : {total / 1024:.1f} KiB")
    usage = shutil.disk_usage(str(WORKSPACE))
    print(f"disk free  : {usage.free / (1024**3):.2f} GiB")
    try:
        state = load_state()
        print(f"last session: {state.get('lastSession')}")
        print(f"last solidified: {state.get('lastConsolidation')}")
    except MemError as exc:
        print(f"STATE ERROR: {exc}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    failures: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
        if ok:
            print(f"[OK]   {name}")
        elif warn_only:
            print(f"[WARN] {name}: {detail}")
            warnings.append(name)
        else:
            print(f"[FAIL] {name}: {detail}")
            failures.append(name)

    print("===== AI-FISH AUDIT =====")
    info = check_seal(cfg)
    check("规则封印", info["status"] == "OK", f"{info['status']}: {info['detail']}")

    core = {
        "RULES.md": BASE / "RULES.md",
        "SELF.md": BASE / "SELF.md",
        "USER.md": BASE / "USER.md",
        "MEMORY.md": BASE / "MEMORY.md",
    }
    for name, path in core.items():
        check(f"核心文件 {name}", path.is_file() and path.stat().st_size > 0, "缺失或为空")
    for name in ("META.md", "SPEC.md"):
        path = BASE / name
        check(f"核心文件 {name}", path.is_file() and path.stat().st_size > 0, "缺失或为空")

    events, raw_errors = all_raw_events()
    check("原始事件可解析", not raw_errors, "; ".join(raw_errors[:3]))
    emap = event_map()
    raw_ids = set(emap)
    done = processed_ids()
    pending = [e for e in events if e[2].get("id") not in done]
    check("未固化事件", not pending, f"{len(pending)} 条待固化", warn_only=True)
    print(f"       events={len(events)} processed={len(done)} pending={len(pending)}")

    daily_files = sorted(DAILY.glob("20??-??-??.md"))
    daily_text = "\n".join(read_text(p) for p in daily_files)

    evt_re = re.compile(r"evt-\d{8}-\d{6}-[0-9a-f]{4}")
    long_missing: list[str] = []
    long_ids: set[str] = set()
    for name in ("MEMORY.md", "SELF.md", "USER.md"):
        text = read_text(BASE / name)
        for lineno, line in enumerate(text.splitlines(), 1):
            for eid in evt_re.findall(line):
                long_ids.add(eid)
                if eid not in raw_ids:
                    long_missing.append(f"{name}:{lineno} {eid}")
    check("长期记忆证据编号存在", not long_missing, "; ".join(long_missing[:5]))

    daily_missing: list[str] = []
    for path in daily_files:
        text = read_text(path)
        for lineno, line in enumerate(text.splitlines(), 1):
            for eid in evt_re.findall(line):
                if eid not in raw_ids:
                    daily_missing.append(f"{rel_posix(path)}:{lineno} {eid}")
    check("日记证据编号存在", not daily_missing, "; ".join(daily_missing[:5]))

    not_in_daily = sorted(eid for eid in long_ids if eid not in daily_text)
    check(
        "长期记忆证据已固化到日记",
        not not_in_daily,
        "未在日记中出现：" + ", ".join(not_in_daily[:5]),
        warn_only=True,
    )

    bad_link = []
    for path in daily_files:
        raw = RAW / f"{path.stem}.jsonl"
        if not raw.is_file() or count_lines(raw) == 0:
            bad_link.append(path.name)
    check("日记有对应原始事件", not bad_link, ", ".join(bad_link[:5]))

    unreferenced = sorted(eid for eid in done if eid not in daily_text)
    check(
        "已固化事件在日记中有引用",
        not unreferenced,
        ", ".join(unreferenced[:5]),
        warn_only=True,
    )

    for path in daily_files:
        lines = {line.strip() for line in read_text(path).splitlines()}
        missing = [s for s in REQUIRED_SECTIONS if s not in lines]
        check(f"日记结构 {path.name}", not missing, "缺 " + "、".join(missing), warn_only=True)

    size_limits = {
        "MEMORY.md": 16000,
        "SELF.md": 16000,
        "USER.md": 16000,
        "RULES.md": 16000,
        "META.md": 6000,
        "SPEC.md": 30000,  # 2026-11-07 审计整改：新增§十七~§二十上调
    }
    for name, limit in size_limits.items():
        size = (BASE / name).stat().st_size if (BASE / name).is_file() else 0
        check(f"体量 {name} <= {limit} B", size <= limit, f"{size} B", warn_only=True)
    for path in daily_files:
        size = path.stat().st_size
        check(f"体量 {rel_posix(path)} <= 64 KiB", size <= 65536, f"{size} B", warn_only=True)

    man_rows, man_errors = read_jsonl(MANIFEST_PATH)
    check("快照清单可解析（审计）", not man_errors, "; ".join(man_errors[:3]), warn_only=True)
    targets = {str(r.get("target")) for r in man_rows}
    for name in core:
        check(f"快照覆盖 {name}", name in targets, "从未快照", warn_only=True)

    for label, path in (("镜像", RULES_MIRROR), ("权威", Path(cfg["canonical_rules"]))):
        if path.is_file():
            writable = bool(path.stat().st_mode & stat.S_IWRITE)
            check(f"{label} RULES 只读", not writable, "当前可写", warn_only=True)
        else:
            check(f"{label} RULES 存在", False, str(path))

    try:
        state = load_state()
        last = (state.get("lastConsolidation") or {}).get("date")
        latest = daily_files[-1].stem if daily_files else None
        check(
            "state 最近固化日期与最新日记一致",
            last == latest,
            f"state={last} latest={latest}",
            warn_only=True,
        )
    except MemError as exc:
        check("state 可解析（审计）", False, str(exc))

    self_text = read_text(BASE / "SELF.md")
    q_count = len(re.findall(r"^- \*\*Q-\d+", self_text, re.MULTILINE))
    check("SELF 保留待验证问题", q_count > 0, "没有 Q 条目", warn_only=True)

    user_text = read_text(BASE / "USER.md")
    check("USER 有纠正记录区", "纠正记录" in user_text, "缺失", warn_only=True)

    dupes: list[str] = []
    for name in ("MEMORY.md", "SELF.md", "USER.md"):
        seen: dict[str, int] = {}
        for lineno, line in enumerate(read_text(BASE / name).splitlines(), 1):
            stripped = line.strip()
            if len(stripped) < 40 or stripped.startswith("#") or stripped == "---":
                continue
            if stripped in seen:
                dupes.append(f"{name}:{lineno} 与 :{seen[stripped]} 重复")
            else:
                seen[stripped] = lineno
    check("长期文件无精确重复行", not dupes, "; ".join(dupes[:3]), warn_only=True)

    print()
    if failures:
        print(f"AUDIT FAIL: {len(failures)} failure(s), {len(warnings)} warning(s)")
        return 1
    print(f"AUDIT PASS ({len(warnings)} warning(s))")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_config()
    ensure_dirs()
    failures: list[str] = []
    warnings: list[str] = []

    def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
        if ok:
            print(f"[OK]   {name}")
        elif warn_only:
            print(f"[WARN] {name}: {detail}")
            warnings.append(name)
        else:
            print(f"[FAIL] {name}: {detail}")
            failures.append(name)

    print("===== AI-FISH VERIFY =====")
    for d in (BASE, DAILY, RAW, INDEX, SNAPSHOTS, ARCHIVE):
        check(f"目录 {rel_posix(d)}", d.is_dir())
    for name in ("RULES.md", "SELF.md", "USER.md", "MEMORY.md", "META.md", "SPEC.md", "config.json"):
        p = BASE / name
        check(f"文件 {name}", p.is_file() and p.stat().st_size > 0, "缺失或为空")
    check("工作区 AGENTS.md", (WORKSPACE / "AGENTS.md").is_file() or (BASE / "AGENTS.md").is_file(), "缺失")
    check(
        "全局 AGENTS.md",
        (Path.home() / ".ai-fish" / "AGENTS.md").is_file() or (Path.home() / ".dsh" / "AGENTS.md").is_file(),
        "缺失（新会话可能不会自动启动记忆流程）",
        warn_only=True,
    )

    info = check_seal(cfg)
    check("规则封印", info["status"] == "OK", f"{info['status']}: {info['detail']}")
    if info["status"] == "MIRROR_MISMATCH":
        print("       -> 运行 `mem.py sync-rules` 从权威文件修复镜像。")
    if LOCAL_SEAL.is_file():
        local_raw = LOCAL_SEAL.read_text(encoding="utf-8-sig").strip()
        local = local_raw.split()[0].lower() if local_raw else ""
        check("工作区封印副本", local == info["expected"], "与权威封印不一致", warn_only=True)

    check("state.json 存在", STATE_PATH.is_file(), "缺失（运行 session-start 会创建）")
    try:
        state = load_state()
        check("state.json 可解析", True)
        check("state 结构", isinstance(state, dict))
    except MemError as exc:
        check("state.json 可解析", False, str(exc))

    events, raw_errors = all_raw_events()
    check("原始事件 JSONL 可解析", not raw_errors, "; ".join(raw_errors[:3]))
    ids = [str(e[2].get("id")) for e in events if e[2].get("id")]
    counts = Counter(ids)
    dupes = sorted(eid for eid, count in counts.items() if count > 1)
    check("原始事件编号唯一", not dupes, ", ".join(dupes[:5]))
    bad_fields = []
    for path, lineno, obj in events:
        for field in ("id", "ts", "date", "kind", "text"):
            if not obj.get(field):
                bad_fields.append(f"{rel_posix(path)}:{lineno} 缺 {field}")
    check("原始事件字段完整", not bad_fields, "; ".join(bad_fields[:5]))
    bad_dates = []
    for path, lineno, obj in events:
        if path.stem != str(obj.get("date", "")):
            bad_dates.append(f"{rel_posix(path)}:{lineno} 日期={obj.get('date')}")
    check("原始事件日期与文件一致", not bad_dates, "; ".join(bad_dates[:5]))

    # 事件级哈希链连续性校验
    broken_chains = []
    if RAW.exists():
        import hashlib
        for raw_file in sorted(RAW.glob("*.jsonl")):
            prev_line_hash = "GENESIS_00000000"
            with raw_file.open("r", encoding="utf-8-sig", errors="replace") as rf:
                for lno, raw_line in enumerate(rf, 1):
                    raw_line_s = raw_line.strip()
                    if not raw_line_s:
                        continue
                    try:
                        ev_obj = json.loads(raw_line_s)
                    except Exception:
                        continue
                    expected_prev = ev_obj.get("prev_hash")
                    if expected_prev is not None:
                        if expected_prev != prev_line_hash and not ev_obj.get("redacted"):
                            broken_chains.append(f"{rel_posix(raw_file)}:{lno} (id={ev_obj.get('id')})")
                    prev_line_hash = hashlib.sha256(raw_line_s.encode("utf-8")).hexdigest()[:16]
    check("原始事件哈希链", not broken_chains, f"链条断裂: {', '.join(broken_chains[:3])}", warn_only=True)

    idx_rows, idx_errors = read_jsonl(EVENTS_INDEX)
    check("events 索引可解析", not idx_errors, "; ".join(idx_errors[:3]), warn_only=True)

    proc_rows, proc_errors = read_jsonl(PROCESSED_PATH)
    check("processed.jsonl 可解析", not proc_errors, "; ".join(proc_errors[:3]))
    known_ids = set(ids)
    unknown_processed = sorted(
        {str(r.get("id")) for r in proc_rows if r.get("id") and str(r.get("id")) not in known_ids}
    )
    check("processed 事件均存在", not unknown_processed, ", ".join(unknown_processed[:5]))

    for daily in sorted(DAILY.glob("20??-??-??.md")):
        text = read_text(daily)
        lines = {line.strip() for line in text.splitlines()}
        missing = [s for s in REQUIRED_SECTIONS if s not in lines]
        check(f"日记结构 {daily.name}", not missing, "缺 " + "、".join(missing), warn_only=True)

    man_rows, man_errors = read_jsonl(MANIFEST_PATH)
    check("快照清单可解析", not man_errors, "; ".join(man_errors[:3]))
    bad_snaps = []
    for row in man_rows:
        snap = BASE / str(row.get("snapshot", ""))
        if not snap.is_file():
            bad_snaps.append(f"缺失 {row.get('snapshot')}")
            continue
        if sha256_file(snap) != row.get("sha256"):
            bad_snaps.append(f"哈希不符 {row.get('snapshot')}")
    check("快照文件完整", not bad_snaps, "; ".join(bad_snaps[:5]))

    free = shutil.disk_usage(str(WORKSPACE)).free
    check("磁盘空间 >= 200 MiB", free >= 200 * 1024 * 1024, f"{free / (1024**2):.0f} MiB")

    try:
        from .db import get_db, get_db_path
        db_p = get_db_path()
        if db_p.is_file():
            conn = get_db()
            integ = conn.execute("PRAGMA integrity_check;").fetchone()[0]
            check("数据库完整性", integ == "ok", f"完整性异常：{integ}", warn_only=True)
            db_ev_c = conn.execute("SELECT count(*) FROM raw_events;").fetchone()[0]
            check("数据库事件同步", db_ev_c == len(events), f"DB记录({db_ev_c})与文本事件({len(events)})不一致，可运行 mem.py db sync 修复", warn_only=True)
            conn.close()
    except Exception as exc:
        check("数据库校验", False, str(exc), warn_only=True)

    print()
    if failures:
        print(f"VERIFY FAIL: {len(failures)} failure(s), {len(warnings)} warning(s)")
        return 1
    print(f"VERIFY PASS ({len(warnings)} warning(s))")
    return 0
