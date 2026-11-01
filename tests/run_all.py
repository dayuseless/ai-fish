#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified test runner executing all ai-fish regression test suites."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

TEST_SUITES = [
    ("meta_selftest.py", "元文档预算与 session-start brief 检查"),
    ("todo_selftest.py", "待办提取与 rollover 跨天账本自测"),
    ("audit_selftest.py", "记忆可追溯性与故障拦截审计自测"),
    ("locktest_concurrency.py", "跨进程文件写锁并发安全自测"),
    ("feature_selftest.py", "口头授权、现场刷新、升格检测等新特性自测"),
    ("failure_injection.py", "故障注入（坏行/缺失/只读篡改）恢复自测"),
    ("db_selftest.py", "轻量级 SQLite 数据库结构化与 FTS 全文索引自测"),
]


def run_suite(script_name: str, verbose: bool = False) -> tuple[bool, float, str]:
    script_path = TESTS_DIR / script_name
    if not script_path.is_file():
        return False, 0.0, f"测试脚本不存在: {script_name}"

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(script_path)],
        cwd=str(TESTS_DIR.parent.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - t0
    output = proc.stdout + proc.stderr
    return proc.returncode == 0, elapsed, output


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 ai-fish 全量回归测试套件")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印详细测试日志")
    parser.add_argument("--fail-fast", action="store_true", help="任意一项失败立即停止")
    args = parser.parse_args()

    print("=" * 60)
    print("开始运行 ai-fish 全量自测回归套件 (共 7 组)")
    print("=" * 60)

    total_start = time.perf_counter()
    results: list[tuple[str, str, bool, float]] = []
    any_failed = False

    for idx, (script, desc) in enumerate(TEST_SUITES, 1):
        print(f"[{idx}/{len(TEST_SUITES)}] {script:<24} | {desc} ... ", end="", flush=True)
        ok, elapsed, out = run_suite(script, verbose=args.verbose)
        if ok:
            print(f"PASS ({elapsed:.1f}s)")
            results.append((script, desc, True, elapsed))
        else:
            print(f"FAIL ({elapsed:.1f}s)")
            results.append((script, desc, False, elapsed))
            any_failed = True
            if not args.verbose:
                print("\n--- 错误输出 ---")
                print(out.strip()[:1000])
                print("----------------\n")
            if args.fail_fast:
                break

        if args.verbose and out.strip():
            print(out.strip())

    total_time = time.perf_counter() - total_start
    print("=" * 60)
    passed_count = sum(1 for r in results if r[2])
    print(f"执行完毕: {passed_count}/{len(results)} 通过，总耗时 {total_time:.1f}s")
    if any_failed:
        print("RESULT: 部分测试失败！")
        return 1
    print("RESULT: ALL 7 TEST SUITES PASSED (全绿)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
