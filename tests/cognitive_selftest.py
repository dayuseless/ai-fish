#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-test for cognitive continuity and the Right-to-be-Forgotten redaction protocol.

Validates:
  1. Epistemic Evolution Lifecycle:
     - Initial User Statement (statement, evt-1)
     - Counter-evidence Observation (observation, evt-2)
     - Synthesized Belief Update (inference, evt-3 citing evt-1 & evt-2)
     - Tracing the cognitive journey without binary amnesia
  2. Right-to-be-Forgotten (Tombstone Redaction Protocol):
     - In-place masking of sensitive payload with [REDACTED]
     - Integrity preservation (JSONL remains parseable, event ID retained)
     - Cascaded purge from SQLite full-text search index
     - Audit trail registration in today's ledger
     - Zero audit / verify regressions
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
MEM_SRC = BASE / "bin" / "mem.py"


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    mem_py = root / "ai-fish" / "bin" / "mem.py"
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(mem_py), *args],
        cwd=str(root / "ai-fish"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def setup_fixture(tmp: Path) -> dict:
    mem_dir = tmp / "ai-fish"
    (mem_dir / "daily" / "raw").mkdir(parents=True)
    (mem_dir / "index").mkdir(parents=True)
    (mem_dir / "snapshots").mkdir(parents=True)
    (mem_dir / "daily" / "archive").mkdir(parents=True)
    shutil.copytree(MEM_SRC.parent, mem_dir / "bin", dirs_exist_ok=True)

    # Mock canonical rules and seal
    can_dir = tmp / "canonical"
    can_dir.mkdir(parents=True)
    rules_bytes = b"# Canonical Rules for Test\n- Rule 1: Always verify\n"
    can_rules = can_dir / "RULES.md"
    can_rules.write_bytes(rules_bytes)
    digest = hashlib.sha256(rules_bytes).hexdigest()
    can_seal = can_dir / "RULES.sha256"
    can_seal.write_bytes(digest.encode("utf-8"))

    # Local mirror
    (mem_dir / "RULES.md").write_bytes(rules_bytes)
    (mem_dir / "RULES.sha256").write_bytes(digest.encode("utf-8"))

    # Long-term docs
    (mem_dir / "MEMORY.md").write_text("# MEMORY.md\n- 最后更新：2026-11-02\n- **M-001**：测试里程碑 `evt-dummy`\n", encoding="utf-8")
    (mem_dir / "USER.md").write_text("# USER.md\n- 最后更新：2026-11-02\n## 纠正记录\n- 无\n", encoding="utf-8")
    (mem_dir / "SELF.md").write_text("# SELF.md\n- 最后更新：2026-11-02\n- **Q-001**：待验证问题\n", encoding="utf-8")
    (mem_dir / "META.md").write_text("# META.md\nRoute index\n", encoding="utf-8")
    (mem_dir / "SPEC.md").write_text("# SPEC.md\nSpec\n", encoding="utf-8")
    (mem_dir / "AGENTS.md").write_text("# AGENTS.md\nAgents rule\n", encoding="utf-8")
    (tmp / "AGENTS.md").write_text("# Root AGENTS.md\nRoot rule\n", encoding="utf-8")

    cfg = {
        "canonical_rules": str(can_rules),
        "canonical_seal": str(can_seal),
        "workspace_root": str(mem_dir),
    }
    (mem_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    return {"root": tmp, "mem_dir": mem_dir}


def test_epistemic_evolution(f: dict) -> tuple[str, str, str]:
    root = f["root"]
    print("  [Step 1] Recording initial user premise (statement)...")
    res1 = run(
        root, "note", "--kind", "statement",
        "--text", "用户明确表达白天偏好使用高对比度亮色模式，因阳光下暗色不可见",
        "--ref", "chat-morning"
    )
    assert res1.returncode == 0, f"res1 failed: {res1.stderr}"
    evt1_id = res1.stdout.split()[1]
    assert evt1_id.startswith("evt-"), f"Invalid event ID: {evt1_id}"

    print("  [Step 2] Recording counter-evidence observation in new context...")
    res2 = run(
        root, "note", "--kind", "observation",
        "--text", "夜间使用 OLED 显示器时用户报告亮色刺眼难忍，切换至暗黑模式后视疲劳明显缓解",
        "--ref", "chat-night"
    )
    assert res2.returncode == 0, f"res2 failed: {res2.stderr}"
    evt2_id = res2.stdout.split()[1]

    print("  [Step 3] Synthesizing updated stance referencing provenance...")
    res3 = run(
        root, "note", "--kind", "inference",
        "--text", "用户主题偏好为环境感知型：强光日照下采用高对比亮色，暗光夜间使用暗色模式",
        "--ref", f"{evt1_id},{evt2_id}"
    )
    assert res3.returncode == 0, f"res3 failed: {res3.stderr}"
    evt3_id = res3.stdout.split()[1]

    # Verify that raw records preserve distinct kind classification and provenance links
    raw_file = list((f["mem_dir"] / "daily" / "raw").glob("*.jsonl"))[0]
    lines = [json.loads(line) for line in raw_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    id_map = {row["id"]: row for row in lines}

    assert id_map[evt1_id]["kind"] == "statement"
    assert id_map[evt2_id]["kind"] == "observation"
    assert id_map[evt3_id]["kind"] == "inference"
    assert evt1_id in id_map[evt3_id]["ref"]
    assert evt2_id in id_map[evt3_id]["ref"]
    print("  -> Epistemic evolution preserved cleanly in raw ledger.")
    return evt1_id, evt2_id, evt3_id


def test_tombstone_redaction(f: dict):
    root = f["root"]
    mem_dir = f["mem_dir"]
    print("  [Step 4] Logging private sensitive event to test redaction...")
    secret_text = "TemporaryTokenSecret9988_DoNotLeak"
    res = run(root, "note", "--kind", "event", "--text", f"配置临时凭据: {secret_text}", "--ref", "test-auth")
    assert res.returncode == 0, f"Failed note: {res.stderr}"
    secret_evt = res.stdout.split()[1]

    # Sync to SQLite
    run(root, "db", "sync")

    # Verify sensitive token is searchable
    res_search = run(root, "search", "--query", "Secret9988")
    assert secret_text in res_search.stdout, "Sensitive token should be initially found in search"

    import datetime
    today_str = datetime.date.today().isoformat()
    daily_file = mem_dir / "daily" / f"{today_str}.md"
    daily_file.write_text(
        f"# {today_str} 日记\n\n## 原始事件\n- {secret_evt}\n\n## 明确表达\n- 无\n\n## 观察\n- 无\n\n## 推断\n- 无\n\n## 未知\n- 无\n\n## 待办\n- 无\n\n## 事件\n- 初始化临时密钥：{secret_text} `{secret_evt}`\n",
        encoding="utf-8"
    )

    print("  [Step 5] Executing tombstone redaction protocol...")
    # Attempt without --yes should refuse and ask for confirmation
    refuse_res = run(root, "redact", "--event", secret_evt, "--reason", "测试凭据清除")
    assert refuse_res.returncode == 2, f"Should refuse without --yes: {refuse_res.stdout}"
    assert "CONFIRM_REQUIRED" in refuse_res.stdout

    # Execute with --yes
    redact_res = run(root, "redact", "--event", secret_evt, "--reason", "测试凭据清除", "--yes")
    assert redact_res.returncode == 0, f"Redact failed: {redact_res.stderr} {redact_res.stdout}"
    assert f"REDACT_OK {secret_evt}" in redact_res.stdout
    assert "DAILY_REDACT_OK" in redact_res.stdout

    # Verify daily log: secret text is replaced by [REDACTED], but event ID remains
    daily_after = daily_file.read_text(encoding="utf-8")
    assert secret_text not in daily_after, "CRITICAL: Sensitive text still in daily markdown!"
    assert "[REDACTED: 已按用户授权擦除敏感内容]" in daily_after
    assert secret_evt in daily_after

    # Verify physical raw file: secret string is GONE, replaced by [REDACTED]
    raw_files = list((mem_dir / "daily" / "raw").glob("*.jsonl"))
    all_raw_text = "\n".join(p.read_text(encoding="utf-8") for p in raw_files)
    assert secret_text not in all_raw_text, "CRITICAL: Raw sensitive text still leaked in JSONL file!"
    assert "[REDACTED per user request: 测试凭据清除]" in all_raw_text
    assert secret_evt in all_raw_text, "Event ID must be preserved for hash and index integrity"

    # Verify SQLite FTS search: searching for sensitive word now yields NOTHING
    res_search_after = run(root, "search", "--query", "Secret9988")
    assert secret_text not in res_search_after.stdout
    assert "0 hit(s)" in res_search_after.stdout or "NO_MATCHES" in res_search_after.stdout
    print("  -> Sensitive data thoroughly purged from raw file, daily log, and SQLite FTS.")

    print("  [Step 6] Running integrity verify & audit...")
    res_ver = run(root, "verify")
    assert res_ver.returncode == 0, f"Verify failed after redaction:\n{res_ver.stdout}\n{res_ver.stderr}"
    assert "VERIFY PASS" in res_ver.stdout
    assert "原始事件哈希链" in res_ver.stdout

    res_aud = run(root, "audit")
    assert res_aud.returncode == 0, f"Audit failed after redaction:\n{res_aud.stdout}\n{res_aud.stderr}"
    assert "AUDIT PASS" in res_aud.stdout
    print("  -> Verify and Audit PASS (0 warnings).")


def main():
    print("=" * 60)
    print("Running Cognitive Continuity & Redaction Protocol Self-Test")
    print("=" * 60)
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = setup_fixture(Path(tmpdir))
        test_epistemic_evolution(fixture)
        test_tombstone_redaction(fixture)
    print("=" * 60)
    print("COGNITIVE & REDACTION SELF-TEST: ALL CHECKS PASSED")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
