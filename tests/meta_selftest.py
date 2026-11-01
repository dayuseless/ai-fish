"""Self-test for META.md / SPEC.md and session-start --brief.

Does not modify memory content; it may update state.json (lastSession)
by invoking session-start, same as a normal startup.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
MEM = BASE / "bin" / "mem.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(MEM), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    meta = BASE / "META.md"
    spec = BASE / "SPEC.md"
    assert meta.is_file(), "META.md missing"
    assert meta.stat().st_size <= 6000, f"META.md too large: {meta.stat().st_size} B"
    text = meta.read_text(encoding="utf-8")
    for needle in ("核心不变量", "触发索引", "SPEC.md"):
        assert needle in text, f"META.md missing: {needle}"

    assert spec.is_file() and spec.stat().st_size > 0, "SPEC.md missing/empty"
    # SPEC 软上限 25 KB：2026-10-31 因新增 §五「归档带现场快照」由 24 KB 上调（commit a920739）。
    assert spec.stat().st_size <= 25000, f"SPEC.md too large: {spec.stat().st_size} B"

    brief = run("session-start", "--brief")
    assert brief.returncode == 0, brief.stderr
    assert len(brief.stdout) < 3000, f"brief too large: {len(brief.stdout)} chars"
    for needle in ("PENDING", "META"):
        assert needle in brief.stdout, f"brief missing: {needle}"

    meta_path = run("meta", "--path")
    assert meta_path.returncode == 0, meta_path.stderr
    assert Path(meta_path.stdout.strip()).name == "META.md"

    full = run("session-start")
    assert full.returncode == 0, full.stderr
    assert len(full.stdout) > len(brief.stdout), "full mode should be larger than brief"

    print(
        "PASS "
        f"brief={len(brief.stdout)}chars "
        f"full={len(full.stdout)}chars "
        f"meta={meta.stat().st_size}B "
        f"spec={spec.stat().st_size}B"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
