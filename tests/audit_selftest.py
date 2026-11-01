import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent  # ai-fish
ROOT = HERE / "audittest"
CLI = ROOT / "bin" / "mem.py"


def force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for item in path.rglob("*"):
        try:
            os.chmod(item, stat.S_IWRITE)
        except OSError:
            pass
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


force_rmtree(ROOT)
(ROOT / "bin").mkdir(parents=True)
for name in ("RULES.md", "SELF.md", "USER.md", "MEMORY.md", "META.md", "SPEC.md", "config.json", "state.json"):
    shutil.copyfile(SOURCE / name, ROOT / name)
shutil.copyfile(SOURCE / "bin" / "mem.py", CLI)
shutil.copytree(SOURCE / "bin" / "lib", ROOT / "bin" / "lib", dirs_exist_ok=True)
for name in ("daily", "index", "snapshots"):
    shutil.copytree(SOURCE / name, ROOT / name)


def run_audit(label: str, expect_fail: bool, expect_text: str = "") -> bool:
    out = HERE / f".audit-{label}.txt"
    with out.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(CLI), "audit"],
            cwd=str(ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    text = out.read_text(encoding="utf-8", errors="replace")
    out.unlink(missing_ok=True)
    failed = proc.returncode != 0
    ok = failed == expect_fail and (not expect_text or expect_text in text)
    print(label, "rc=", proc.returncode, "expected_fail=", expect_fail, "ok=", ok)
    if not ok:
        print(text[-2000:])
    return ok


results = []
results.append(run_audit("baseline", False))
self_path = ROOT / "SELF.md"
original_self = self_path.read_text(encoding="utf-8")
self_path.write_text(
    original_self
    + "\n- **F-999｜伪造证据测试**：这条引用了不存在的 evt-20260101-000000-dead。\n",
    encoding="utf-8",
)
results.append(run_audit("fake-evidence", True, "长期记忆证据编号存在"))
self_path.write_text(original_self, encoding="utf-8")

daily = ROOT / "daily" / "2026-10-25.md"
daily.write_text(
    "# 2026-10-25 日记\n\n"
    "## 事件\n- 无原始事件\n## 明确表达\n- 无\n## 观察\n- 无\n"
    "## 推断\n- 无\n## 未知\n- 无\n## 待办\n- 无\n",
    encoding="utf-8",
)
# 只有日记、没有对应 raw 原始事件：必须被判为失败（孤儿日记）
results.append(run_audit("orphan-daily", True, "日记有对应原始事件"))
daily.unlink(missing_ok=True)

force_rmtree(ROOT)
if all(results):
    print("AUDIT_SELFTEST_PASS")
    sys.exit(0)
print("AUDIT_SELFTEST_FAIL")
sys.exit(1)
