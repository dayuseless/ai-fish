# -*- coding: utf-8 -*-
"""ai-fish seal and rules verification/synchronization."""
from __future__ import annotations

import argparse
import os
import re
import stat
from pathlib import Path

from .core import (
    ALLOWED_SEAL_STATUS,
    BASE,
    RULES_MIRROR,
    atomic_write_bytes,
    load_config,
    memory_lock,
    rel_posix,
    sha256_file,
)


def check_seal(cfg: dict) -> dict:
    rules = Path(cfg["canonical_rules"])
    seal = Path(cfg["canonical_seal"])
    if not rules.is_absolute():
        rules = (BASE / rules).resolve()
    if not seal.is_absolute():
        seal = (BASE / seal).resolve()
    info: dict = {
        "status": "UNKNOWN",
        "canonical": str(rules),
        "seal_file": str(seal),
        "expected": None,
        "actual": None,
        "mirror": None,
        "detail": "",
    }
    if not rules.is_file():
        info["status"] = "MISSING_CANONICAL"
        info["detail"] = "权威 RULES.md 不存在"
        return info
    info["actual"] = sha256_file(rules)
    if not seal.is_file():
        info["status"] = "MISSING_SEAL"
        info["detail"] = "权威封印文件不存在"
        return info
    try:
        raw = seal.read_text(encoding="utf-8-sig").strip()
        expected = raw.split()[0].lower() if raw else ""
    except OSError as exc:
        info["status"] = "MISSING_SEAL"
        info["detail"] = f"读取封印失败：{exc}"
        return info
    info["expected"] = expected
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        info["status"] = "INVALID_SEAL"
        info["detail"] = "封印不是 64 位十六进制 SHA-256"
        return info
    if expected != info["actual"]:
        info["status"] = "MISMATCH"
        info["detail"] = "权威 RULES.md 的 SHA-256 与封印不一致"
        return info
    if not RULES_MIRROR.is_file():
        info["status"] = "MIRROR_MISSING"
        info["detail"] = "工作区镜像 RULES.md 不存在"
        return info
    info["mirror"] = sha256_file(RULES_MIRROR)
    if info["mirror"] != info["actual"]:
        info["status"] = "MIRROR_MISMATCH"
        info["detail"] = "权威文件正常，但工作区镜像与权威文件不一致"
        return info
    info["status"] = "OK"
    info["detail"] = "权威文件与镜像一致"
    return info


def require_seal(cfg: dict) -> dict:
    info = check_seal(cfg)
    if info["status"] not in ALLOWED_SEAL_STATUS:
        print(f"SEAL {info['status']}: {info['detail']}")
        print("拒绝写入记忆。请按 RULES.md 第 5/6 节向用户报告并等待处理。")
        raise SystemExit(3)
    if info["status"] == "MIRROR_MISMATCH":
        print(f"WARN: {info['detail']}；可运行 `mem.py sync-rules` 从权威文件修复镜像。")
    return info


def print_seal(info: dict) -> None:
    print(f"SEAL {info['status']}: {info['detail']}")
    print(f"  canonical: {info['canonical']}")
    print(f"  expected : {info['expected']}")
    print(f"  actual   : {info['actual']}")
    print(f"  mirror   : {info['mirror']}")


def cmd_sync_rules(args: argparse.Namespace) -> int:
    cfg = load_config()
    info = check_seal(cfg)
    if info["status"] in ("MISMATCH", "MISSING_CANONICAL", "MISSING_SEAL", "INVALID_SEAL"):
        print(f"REFUSED: 权威规则不可信（{info['status']}: {info['detail']}）。")
        return 3
    canonical = Path(cfg["canonical_rules"])
    digest = sha256_file(canonical)
    with memory_lock():
        if RULES_MIRROR.exists() and sha256_file(RULES_MIRROR) == digest:
            print("SYNC_NOOP: 镜像已与权威文件一致。")
            return 0
        if RULES_MIRROR.exists():
            from .storage import snapshot_file
            snapshot_file("RULES.md", "sync-rules 前保留漂移镜像")
        atomic_write_bytes(RULES_MIRROR, canonical.read_bytes())
        os.chmod(RULES_MIRROR, stat.S_IREAD)
        if sha256_file(RULES_MIRROR) != digest:
            from .core import MemError
            raise MemError("同步后镜像哈希不一致")
        print(f"SYNC_OK {rel_posix(RULES_MIRROR)} sha256={digest}")
    return 0
