# -*- coding: utf-8 -*-
"""Unit and regression tests for qq-digest-auto.mjs batch transaction & idempotency."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

def test_batch_pipeline():
    with tempfile.TemporaryDirectory(prefix="ai-fish-digest-tx-") as tmpdir:
        tmp = Path(tmpdir)
        aifish = tmp / "ai-fish"
        inbox = aifish / "inbox"
        index = aifish / "index"
        raw = aifish / "daily" / "raw"
        inbox.mkdir(parents=True)
        index.mkdir(parents=True)
        raw.mkdir(parents=True)
        
        # Copy bin directory
        shutil.copytree(BASE / "bin", aifish / "bin", dirs_exist_ok=True)
        
        # Create minimal config and seal
        rules = b"# Rules\n"
        can_rules = tmp / "RULES.md"
        can_rules.write_bytes(rules)
        import hashlib
        can_seal = tmp / "RULES.sha256"
        can_seal.write_bytes(hashlib.sha256(rules).hexdigest().encode("utf-8"))
        
        (aifish / "RULES.md").write_bytes(rules)
        (aifish / "index" / "rules.sha256").write_text(f"{hashlib.sha256(rules).hexdigest()}  RULES.md\n", encoding="utf-8")
        
        cfg = {
            "version": 1,
            "workspace": str(tmp),
            "canonical_rules": str(can_rules),
            "canonical_seal": str(can_seal),
        }
        (aifish / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (aifish / "state.json").write_text(json.dumps({}), encoding="utf-8")
        (aifish / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (tmp / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (aifish / "MEMORY.md").write_text("# MEMORY.md\n\n## 1. 事项\n- 记忆项\n", encoding="utf-8")
        (aifish / "USER.md").write_text("# USER.md\n\n## 偏好\n- 偏好项\n", encoding="utf-8")
        (aifish / "SELF.md").write_text("# SELF.md\n\n## 设定\n- 设定项\n", encoding="utf-8")
        (aifish / "META.md").write_text("# META.md\n元文档\n", encoding="utf-8")
        (aifish / "SPEC.md").write_text("# SPEC.md\n规范\n", encoding="utf-8")
        
        # Create material files
        mat1 = inbox / "qq-chat1.md"
        mat1.write_text("# Chat 1\nUser: Hello\n", encoding="utf-8")
        mat2 = inbox / "qq-chat2.md"
        mat2.write_text("# Chat 2\nUser: World\n", encoding="utf-8")
        
        env = dict(os.environ)
        env["MEM_DIR"] = str(tmp)
        
        # --- TEST 1: REJECTION (Invalid manifest) ---
        bad_apply1 = inbox / "apply-20261107-100000.jsonl"
        bad_apply1.write_text('{"files": ["invalid_path.exe"]}\n{"kind":"event","text":"ok"}\n', encoding="utf-8")
        
        res1 = subprocess.run(
            ["node", str(aifish / "bin" / "qq-digest-auto.mjs"), "--apply-only"],
            cwd=str(tmp),
            env=env,
            capture_output=True,
            text=True,
        )
        assert mat1.is_file(), "Material 1 must not be deleted on rejection"
        assert mat2.is_file(), "Material 2 must not be deleted on rejection"
        assert bad_apply1.is_file(), "Bad apply file must not be deleted on rejection"
        
        batches_log = index / "digest-batches.jsonl"
        assert batches_log.is_file(), "digest-batches.jsonl must exist"
        b_lines = [json.loads(line) for line in batches_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(b.get("status") == "rejected" and b.get("file") == "apply-20261107-100000.jsonl" for b in b_lines)
        bad_apply1.unlink()
        
        # --- TEST 2: REJECTION (Invalid line record) ---
        bad_apply2 = inbox / "apply-20261107-100100.jsonl"
        bad_apply2.write_text('{"files": ["qq-chat1.md"]}\n{"invalid_json": true\n', encoding="utf-8")
        
        res2 = subprocess.run(
            ["node", str(aifish / "bin" / "qq-digest-auto.mjs"), "--apply-only"],
            cwd=str(tmp),
            env=env,
            capture_output=True,
            text=True,
        )
        assert mat1.is_file(), "Material 1 must not be deleted on record validation failure"
        assert bad_apply2.is_file(), "Apply file must not be deleted on record validation failure"
        bad_apply2.unlink()
        
        # --- TEST 3: VALID BATCH (Full Transaction Commit) ---
        good_apply = inbox / "apply-20261107-100200.jsonl"
        good_apply.write_text(
            '{"files": ["qq-chat1.md", "qq-chat2.md"]}\n'
            '{"kind": "statement", "text": "用户明确表示批次事务已正常工作", "ref": "qq-digest chat"}\n'
            '{"kind": "event", "text": "完成 QQ 记忆提炼落库测试", "ref": "qq-digest chat"}\n',
            encoding="utf-8"
        )
        
        res3 = subprocess.run(
            ["node", str(aifish / "bin" / "qq-digest-auto.mjs"), "--apply-only"],
            cwd=str(tmp),
            env=env,
            capture_output=True,
            text=True,
        )
        assert not mat1.exists(), "Material 1 should be unlinked after full commit"
        assert not mat2.exists(), "Material 2 should be unlinked after full commit"
        assert not good_apply.exists(), "Apply file should be unlinked after full commit"
        
        b_lines = [json.loads(line) for line in batches_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        committed_b = [b for b in b_lines if b.get("status") == "committed" and b.get("file") == "apply-20261107-100200.jsonl"]
        assert len(committed_b) == 1, "Must have exactly 1 committed record in digest-batches.jsonl"
        assert committed_b[0]["records"] == 2
        assert committed_b[0]["written"] == 2
        
        raw_files = list(raw.glob("*.jsonl"))
        assert len(raw_files) >= 1
        raw_text = "\n".join(rf.read_text(encoding="utf-8") for rf in raw_files)
        assert "用户明确表示批次事务已正常工作" in raw_text
        assert "完成 QQ 记忆提炼落库测试" in raw_text

    print("PASS qq-digest batch transaction & idempotency verified!")
    return 0

if __name__ == "__main__":
    sys.exit(test_batch_pipeline())
