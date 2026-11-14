"""Self-test for `mem.py todo`（待办汇总 + 已办账本）。

在临时目录里造一份最小记忆库跑，不触碰真实日记与真实 index/todo-done.jsonl；
最后对真实记忆库跑一次只读 `todo --days 1`，检查输出体量（token 预算回归）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MEM_SRC = BASE / "bin" / "mem.py"

FIXTURE_DAY1 = """# 2026-01-01 日记

## 固化批次 2026-01-01T10:00:00+08:00

## 待办

- 甲：第一条待办，带证据。`evt-20260101-100000-aaaa`
- 乙：重复出现的待办。
- （无）

## 固化批次 2026-01-01T11:00:00+08:00

## 待办

- 乙：重复出现的待办。
- 丙：折行待办第一段
  续行第二段
"""

FIXTURE_DAY2 = """# 2026-01-02 日记

## 固化批次 2026-01-02T09:00:00+08:00

## 待办

- 丁：第二天的新待办。
"""


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "ai-fish" / "bin" / "mem.py"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mem-todo-"))
    try:
        (tmp / "ai-fish" / "daily").mkdir(parents=True)
        shutil.copytree(MEM_SRC.parent, tmp / "ai-fish" / "bin", dirs_exist_ok=True)
        (tmp / "ai-fish" / "daily" / "2026-01-01.md").write_text(FIXTURE_DAY1, encoding="utf-8")
        (tmp / "ai-fish" / "daily" / "2026-01-02.md").write_text(FIXTURE_DAY2, encoding="utf-8")

        # 1) 默认全量：3 条（甲/乙/丙/丁 去重后 4 条，按日期倒序）
        out = run(tmp, "todo", "--all")
        assert out.returncode == 0, out.stderr or out.stdout
        assert "4 条" in out.stdout, f"expect 4 unique todos, got: {out.stdout}"
        assert "续行第二段" in out.stdout, "折行续行没有并入上一条"
        assert "（无）" not in out.stdout, "占位符不该出现在待办里"
        assert out.stdout.index("丁") < out.stdout.index("甲"), "应按日期倒序"

        # 2) 去重：乙 出现两次，只保留最新批次那次
        assert out.stdout.count("乙：重复出现的待办") == 1, "重复待办未去重"

        # 3) --days 过滤：只看近 1 天（相对真实当前日期，两天都在过去 ⇒ 0 条）
        recent = run(tmp, "todo", "--days", "1")
        assert recent.returncode == 0, recent.stderr
        assert "NO_TODO" in recent.stdout, f"过期日记应被 --days 过滤: {recent.stdout}"

        # 4) --json 可解析
        js = run(tmp, "todo", "--all", "--json")
        assert js.returncode == 0, js.stderr
        payload = json.loads(js.stdout)
        assert payload["count"] == 4, payload
        assert len(payload["todos"]) == 4

        # 5) --done 标记后从列表消失，--include-done 能看到 (已办)
        first = run(tmp, "todo", "--all", "--done", "1")
        assert first.returncode == 0, first.stderr or first.stdout
        assert "DONE_OK 1" in first.stdout, first.stdout
        after = run(tmp, "todo", "--all")
        assert "3 条" in after.stdout, f"标记后应剩 3 条: {after.stdout}"
        shown = run(tmp, "todo", "--all", "--include-done")
        assert "(已办)" in shown.stdout, "已办标记没有显示"

        # 6) 越界序号报错而不是静默
        bad = run(tmp, "todo", "--all", "--done", "99")
        assert bad.returncode == 1 and "序号无效" in bad.stdout, bad.stdout

        # 7) 已办账本只追加、可解析
        ledger = tmp / "ai-fish" / "index" / "todo-done.jsonl"
        rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert len(rows) == 1 and rows[0]["key"].startswith("2026-01-02|"), rows
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 8) 真实库只读回归：输出体量必须显著小于整篇 MEMORY.md + 日记
    real = run(BASE.parent, "todo", "--days", "1", "--max-chars", "120")
    assert real.returncode == 0, real.stderr
    assert len(real.stdout) < 6000, f"todo 输出过大，失去省 token 的意义：{len(real.stdout)} chars"

    print(f"PASS todo selftest（真实库输出 {len(real.stdout)} chars）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
