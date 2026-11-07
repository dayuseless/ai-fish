"""Self-test for newly implemented features in mem.py:
  1. `grant` (oral approvals tracking)
  2. `sync-resume` (lightweight scene snapshot refresh for pending events)
  3. `promote-check` (consolidation candidates detection)
  4. `todo --rollover` (past pending tasks rollover with age tags)

Runs against an isolated temporary memory repository to avoid mutating live data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MEM_SRC = BASE / "bin" / "mem.py"


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "ai-fish" / "bin" / "mem.py"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def setup_fixture(tmp: Path) -> dict:
    (tmp / "ai-fish" / "daily" / "raw").mkdir(parents=True)
    (tmp / "ai-fish" / "index").mkdir(parents=True)
    shutil.copytree(MEM_SRC.parent, tmp / "ai-fish" / "bin", dirs_exist_ok=True)

    # Mock canonical rules and seal
    can_dir = tmp / "canonical"
    can_dir.mkdir(parents=True)
    rules_bytes = b"# Mock Rules\n"
    can_rules = can_dir / "RULES.md"
    can_rules.write_bytes(rules_bytes)
    import hashlib
    digest = hashlib.sha256(rules_bytes).hexdigest()
    can_seal = can_dir / "RULES.sha256"
    can_seal.write_bytes(digest.encode("utf-8"))

    # Local mirror
    (tmp / "ai-fish" / "RULES.md").write_bytes(rules_bytes)

    # Local config.json pointing to canonical rules & seal
    cfg = {
        "version": 1,
        "workspace": str(tmp),
        "canonical_rules": str(can_rules),
        "canonical_seal": str(can_seal),
        "max_note_chars": 12000,
        "max_search_results": 80,
    }
    (tmp / "ai-fish" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    # Core markdown files
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    three_days_ago = (datetime.now().date() - timedelta(days=3)).isoformat()

    (tmp / "ai-fish" / "MEMORY.md").write_text(
        f"# MEMORY.md\n- 最后更新：{three_days_ago}\n\n## 1. 运行环境\n已核实环境。\n",
        encoding="utf-8",
    )
    (tmp / "ai-fish" / "USER.md").write_text(
        f"# USER.md\n- 最后更新：{three_days_ago}\n\n## 纠正记录\n无。\n",
        encoding="utf-8",
    )
    (tmp / "ai-fish" / "SELF.md").write_text(
        f"# SELF.md\n- 最后更新：{three_days_ago}\n\n- **Q-001**：测试问题。\n",
        encoding="utf-8",
    )
    (tmp / "ai-fish" / "META.md").write_text("# META.md\n入口\n", encoding="utf-8")
    (tmp / "ai-fish" / "SPEC.md").write_text("# SPEC.md\n细则\n", encoding="utf-8")

    # Past daily log with todo, inference, statement, and milestone
    past_daily = f"""# {yesterday} 日记

## 固化批次 {yesterday}T12:00:00+08:00

## 事件

- 成功部署测试插件并上线运行。`evt-{yesterday.replace('-', '')}-120000-0001`

## 明确表达

- 用户明确要求：“所有自动化配置必须先经过口头批准再落地。”

## 观察

- 系统运行平稳。

## 推断

- 高置信推断：外部审批流需要与本地授权打通方能避免阻塞。

## 未知

- （无）

## 待办

- 昨日遗留待办：检查新插件日志并确认无异常。
"""
    (tmp / "ai-fish" / "daily" / f"{yesterday}.md").write_text(past_daily, encoding="utf-8")

    # Today daily log
    today_daily = f"""# {today} 日记

## 固化批次 {today}T10:00:00+08:00

## 事件

- 今日正常启动。

## 明确表达

- （无）

## 观察

- （无）

## 推断

- （无）

## 未知

- （无）

## 待办

- 今日专属待办：安排下午代码复盘。
"""
    (tmp / "ai-fish" / "daily" / f"{today}.md").write_text(today_daily, encoding="utf-8")

    return {
        "yesterday": yesterday,
        "today": today,
    }


def test_grant_lifecycle(tmp: Path) -> None:
    # 1. 初始列表为空
    res = run(tmp, "grant", "--list")
    assert res.returncode == 0, res.stderr
    assert "0 active" in res.stdout, res.stdout

    # 2. 缺少 --topic 时报错
    res = run(tmp, "grant")
    assert res.returncode != 0, "缺少 --topic 应失败"

    # 3. 添加新授权
    res = run(
        tmp,
        "grant",
        "--topic",
        "安装 ffmpeg",
        "--ref",
        "evt-20261101-test",
        "--note",
        "用户口头批准",
    )
    assert res.returncode == 0, f"stdout: {res.stdout}, stderr: {res.stderr}"
    assert "GRANT_OK" in res.stdout, res.stdout
    assert "安装 ffmpeg" in res.stdout

    # 4. 模糊与精确查询
    res = run(tmp, "grant", "--check", "FFMPEG")
    assert res.returncode == 0, res.stderr
    assert "GRANT_FOUND" in res.stdout
    assert "安装 ffmpeg" in res.stdout

    res_miss = run(tmp, "grant", "--check", "nonexistent")
    assert res_miss.returncode == 0
    assert "GRANT_NOT_FOUND" in res_miss.stdout

    # 5. 列表应有 1 条
    res = run(tmp, "grant", "--list")
    assert res.returncode == 0
    assert "1 active" in res.stdout

    # 提取 grant ID
    import re
    match = re.search(r"\[(grant-\d+-\d+-[0-9a-f]+)\]", res.stdout)
    assert match, f"未提取到 grant ID: {res.stdout}"
    gid = match.group(1)

    # 6. 撤销授权
    res = run(tmp, "grant", "--revoke", gid)
    assert res.returncode == 0, res.stderr
    assert "GRANT_REVOKED" in res.stdout

    # 7. 撤销后查询不再命中
    res = run(tmp, "grant", "--check", "ffmpeg")
    assert "GRANT_NOT_FOUND" in res.stdout

    res = run(tmp, "grant", "--list")
    assert "0 active" in res.stdout
    assert "revoked" in res.stdout

    # 8. 撤销不存在的 ID 报错
    res_bad = run(tmp, "grant", "--revoke", "grant-fake-id")
    assert res_bad.returncode != 0


def test_sync_resume(tmp: Path) -> None:
    # 1. 没有 pending 事件且无 --force 时 NOOP
    res = run(tmp, "sync-resume")
    assert res.returncode == 0, f"rc={res.returncode}, out={res.stdout}, err={res.stderr}"
    assert "SYNC_RESUME_NOOP" in res.stdout, f"got: {res.stdout}, err: {res.stderr}"

    # 2. 模拟写入一个 raw pending 事件
    event = {
        "id": "evt-20261101-999999-test",
        "ts": "2026-11-01T12:00:00+08:00",
        "date": "2026-11-01",
        "kind": "event",
        "actor": "user",
        "text": "测试未固化事件：用户准备进行跨会话接续",
        "ref": "",
        "tags": [],
    }
    raw_file = tmp / "ai-fish" / "daily" / "raw" / "2026-11-01.jsonl"
    raw_file.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")

    # 3. 创建旧 resume.md
    old_resume = """# 现场快照
- 归档时间：2026-10-31T20:00:00+08:00

---

## 在做
- 正在进行测试验证

## 已定
- 核心功能保持稳定

## 下一步
- 运行最终验收测试

## 悬着
- 无
"""
    (tmp / "ai-fish" / "index" / "resume.md").write_text(old_resume, encoding="utf-8")

    # 4. 执行 sync-resume
    res = run(tmp, "sync-resume")
    assert res.returncode == 0, res.stderr
    assert "SYNC_RESUME_OK" in res.stdout
    assert "pending=1" in res.stdout

    # 5. 校验新 resume.md 内容
    new_resume = (tmp / "ai-fish" / "index" / "resume.md").read_text(encoding="utf-8")
    assert "正在进行测试验证" in new_resume, "未保留【在做】章节"
    assert "核心功能保持稳定" in new_resume, "未保留【已定】章节"
    assert "运行最终验收测试" in new_resume, "未保留【下一步】章节"
    assert "evt-20261101-999999-test" in new_resume, "未把 pending 事件写入【悬着】"
    assert len(new_resume) <= 1200, "超出了 RESUME_MAX_CHARS"


def test_promote_check(tmp: Path) -> None:
    # 运行 promote-check
    res = run(tmp, "promote-check", "--days", "5")
    assert res.returncode == 0, res.stderr
    assert "PROMOTE_CHECK" in res.stdout
    # MEMORY / USER / SELF 都设置在 3 天前，应报 STALE
    assert "STALE: MEMORY.md" in res.stdout
    assert "STALE: USER.md" in res.stdout
    assert "STALE: SELF.md" in res.stdout
    # 候选项应包含高置信推断或重要表达/事件
    assert "CANDIDATES" in res.stdout

    # JSON 模式
    res_json = run(tmp, "promote-check", "--days", "5", "--json")
    assert res_json.returncode == 0
    data = json.loads(res_json.stdout)
    assert len(data["stale"]) == 3
    assert len(data["candidates"]) >= 1


def test_todo_rollover(tmp: Path, dates: dict) -> None:
    # 1. 运行普通 todo，看到所有待办（包含今天和昨天）
    res_all = run(tmp, "todo", "--all")
    assert res_all.returncode == 0
    assert "昨日遗留待办" in res_all.stdout
    assert "今日专属待办" in res_all.stdout

    # 2. 运行 todo --rollover，只应该展示今天之前的待办（昨日遗留待办），且带天数标记
    res_roll = run(tmp, "todo", "--rollover")
    assert res_roll.returncode == 0
    assert "滚转（今日之前未完成）" in res_roll.stdout
    assert "昨日遗留待办" in res_roll.stdout
    assert "今日专属待办" not in res_roll.stdout, "今日待办不应出现在 rollover 中"
    assert "⏰1d" in res_roll.stdout, "应带有 1 天时滞标记"


def test_note_idempotency(tmp: Path) -> None:
    res1 = run(tmp, "note", "--kind", "event", "--text", "幂等测试事件001", "--ref", "ref-idemp-1", "--idempotent")
    assert res1.returncode == 0, f"res1 failed: {res1.stdout} {res1.stderr}"
    assert "NOTE_OK" in res1.stdout
    evt_id = res1.stdout.split()[1]

    # 携带 --idempotent 写入相同特征的事件，应当返回 NOTE_IDEMPOTENT_SKIP 且不追加重复行
    res2 = run(tmp, "note", "--kind", "event", "--text", "幂等测试事件001", "--ref", "ref-idemp-1", "--idempotent")
    assert res2.returncode == 0, f"res2 failed: {res2.stdout} {res2.stderr}"
    assert "NOTE_IDEMPOTENT_SKIP" in res2.stdout
    assert evt_id in res2.stdout

    # 验证物理文件中只存在唯一一条该事件
    raw_files = list((tmp / "ai-fish" / "daily" / "raw").glob("*.jsonl"))
    assert len(raw_files) >= 1
    content = "\n".join(f.read_text(encoding="utf-8") for f in raw_files)
    assert content.count("幂等测试事件001") == 1


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mem-feat-"))
    try:
        dates = setup_fixture(tmp)
        print("1. Testing grant lifecycle...")
        test_grant_lifecycle(tmp)
        print("   PASS: grant lifecycle")

        print("2. Testing sync-resume...")
        test_sync_resume(tmp)
        print("   PASS: sync-resume")

        print("3. Testing promote-check...")
        test_promote_check(tmp)
        print("   PASS: promote-check")

        print("4. Testing todo --rollover...")
        test_todo_rollover(tmp, dates)
        print("   PASS: todo --rollover")

        print("5. Testing note --idempotent...")
        test_note_idempotency(tmp)
        print("   PASS: note --idempotent")

        print("\nALL FEATURE SELFTESTS PASSED!")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
