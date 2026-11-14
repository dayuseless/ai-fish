#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprehensive self-test suite for ai-fish lightweight SQLite database integration."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEM_SRC = (HERE.parent / "bin" / "mem.py") if (HERE.parent / "bin" / "mem.py").is_file() else (HERE.parent.parent / "ai-fish" / "bin" / "mem.py")


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "ai-fish" / "bin" / "mem.py"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_db_workflow():
    with tempfile.TemporaryDirectory(prefix="ai-fish-db-test-") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "ai-fish" / "daily" / "raw").mkdir(parents=True)
        (tmp / "ai-fish" / "index").mkdir(parents=True)
        (tmp / "ai-fish" / "snapshots").mkdir(parents=True)
        shutil.copytree(MEM_SRC.parent, tmp / "ai-fish" / "bin", dirs_exist_ok=True)

        # Mock canonical rules and seal
        can_dir = tmp / "canonical"
        can_dir.mkdir(parents=True)
        rules_bytes = b"# Mock Rules\n"
        can_rules = can_dir / "RULES.md"
        can_rules.write_bytes(rules_bytes)
        digest = hashlib.sha256(rules_bytes).hexdigest()
        can_seal = can_dir / "RULES.sha256"
        can_seal.write_bytes(digest.encode("utf-8"))

        # Local mirror & local seal
        (tmp / "ai-fish" / "RULES.md").write_bytes(rules_bytes)
        (tmp / "ai-fish" / "index" / "rules.sha256").write_text(f"{digest}  RULES.md\n", encoding="utf-8")

        cfg = {
            "version": 1,
            "workspace": str(tmp),
            "canonical_rules": str(can_rules),
            "canonical_seal": str(can_seal),
            "max_note_chars": 12000,
            "max_search_results": 50,
        }
        (tmp / "ai-fish" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (tmp / "ai-fish" / "state.json").write_text(json.dumps({}), encoding="utf-8")

        # Mock long-term docs
        (tmp / "ai-fish" / "SELF.md").write_text(
            "# SELF.md — 自我认识\n\n- 版本：0.14\n\n## 已确认的事实（F）\n\n- **F-001｜运行环境**：Windows 10 Python 3.14。\n  - 证据：evt-20261027-001\n",
            encoding="utf-8",
        )
        (tmp / "ai-fish" / "USER.md").write_text(
            "# USER.md — 关于用户\n\n- 版本：1.2\n\n## 用户明确表达（U）\n\n- **U-009｜不汇报记忆写入**：内部写入不向用户汇报。\n  - 来源：evt-20261028-001\n",
            encoding="utf-8",
        )
        (tmp / "ai-fish" / "MEMORY.md").write_text(
            "# MEMORY.md — 长期记忆\n\n- 版本：0.16\n\n## 3. 事项状态\n\n- **M-009｜记忆工具链功能扩展与模块化解耦**：拆分子模块并部署数据库。\n  - 证据：evt-20261101-001\n",
            encoding="utf-8",
        )
        (tmp / "ai-fish" / "SPEC.md").write_text("# SPEC.md\n\n## 一、总则\n\n- 规范内容\n", encoding="utf-8")
        (tmp / "ai-fish" / "META.md").write_text("# META.md\n\n元文档内容\n", encoding="utf-8")

        # 1. Note raw events
        res = run(tmp, "note", "--kind", "observation", "--text", "测试事件A：工具链解耦验证", "--tag", "解耦")
        assert res.returncode == 0, f"note A failed: stdout={res.stdout}, stderr={res.stderr}"

        res = run(tmp, "note", "--kind", "event", "--text", "测试事件B：数据库部署与自测", "--tag", "数据库")
        assert res.returncode == 0, f"note B failed: stdout={res.stdout}, stderr={res.stderr}"

        # 2. Test db status before sync
        res = run(tmp, "db", "status")
        assert res.returncode == 0
        assert "数据库未就绪" in res.stdout

        # 3. Test db sync
        res = run(tmp, "db", "sync")
        assert res.returncode == 0, f"db sync failed: stdout={res.stdout}, stderr={res.stderr}"
        assert "DB_SYNC_OK" in res.stdout
        assert "长期记忆条目:" in res.stdout

        # Verify DB file exists
        db_file = tmp / "ai-fish" / "index" / "memory.db"
        assert db_file.is_file(), "memory.db was not created!"

        # 4. Test db status after sync
        res = run(tmp, "db", "status")
        assert res.returncode == 0
        assert "完整性校验 : ok" in res.stdout
        assert "原始事件记录: 2" in res.stdout

        # 5. Test db get
        res = run(tmp, "db", "get", "F-001")
        assert res.returncode == 0, f"db get F-001 failed: {res.stdout}"
        assert "运行环境" in res.stdout
        assert "SELF.md" in res.stdout

        res = run(tmp, "db", "get", "U-009")
        assert res.returncode == 0
        assert "不汇报记忆写入" in res.stdout

        # 6. Test db query (SELECT)
        res = run(tmp, "db", "query", "SELECT doc, count(*) FROM long_term_items GROUP BY doc")
        assert res.returncode == 0
        assert "Query Result" in res.stdout

        # Test db query security guard (non-SELECT rejection)
        res = run(tmp, "db", "query", "DROP TABLE long_term_items")
        assert res.returncode != 0
        assert "仅允许只读 SELECT" in res.stdout or "仅允许只读 SELECT" in res.stderr

        # 7. Test db events
        res = run(tmp, "db", "events", "--pending")
        assert res.returncode == 0
        assert "RAW_EVENTS (2 条匹配):" in res.stdout

        # 8. Test FTS search via mem.py search
        res = run(tmp, "search", "--query", "解耦")
        assert res.returncode == 0, f"search failed: {res.stdout}"
        assert "FTS5" in res.stdout
        assert "M-009" in res.stdout

        # Test text-only fallback flag
        res = run(tmp, "search", "--query", "解耦", "--text-only")
        assert res.returncode == 0
        assert "FTS5" not in res.stdout
        assert "M-009" in res.stdout

        # 9. Test real-time incremental note insertion into DB
        res = run(tmp, "note", "--kind", "statement", "--text", "增量实时事件测试：即写即查", "--tag", "实时")
        assert res.returncode == 0

        # Query immediately via search without manual sync
        res = run(tmp, "search", "--query", "即写即查")
        assert res.returncode == 0
        assert "FTS5" in res.stdout
        assert "即写即查" in res.stdout

        # 10. Test DB removal & fallback resilience
        db_file.unlink()
        assert not db_file.exists()
        res = run(tmp, "search", "--query", "即写即查")
        assert res.returncode == 0
        assert "即写即查" in res.stdout  # Falls back to text search seamlessly!

        # 11. Test rebuild from text
        res = run(tmp, "db", "sync", "--rebuild")
        assert res.returncode == 0
        assert db_file.is_file()

        res = run(tmp, "search", "--query", "即写即查")
        assert res.returncode == 0
        assert "FTS5" in res.stdout

        # 12. Test visibility scoping (--scope public vs admin)
        res_pub_u = run(tmp, "search", "--query", "不汇报记忆写入", "--scope", "public")
        assert res_pub_u.returncode == 0
        assert "0 hit(s)" in res_pub_u.stdout or "NO_MATCHES" in res_pub_u.stdout

        res_adm_u = run(tmp, "search", "--query", "不汇报记忆写入", "--scope", "admin")
        assert res_adm_u.returncode == 0
        assert "U-009" in res_adm_u.stdout

        res_pub_get_u = run(tmp, "db", "get", "U-009", "--scope", "public")
        assert res_pub_get_u.returncode != 0
        assert "未在长期记忆数据库中找到条目" in res_pub_get_u.stdout

        res_pub_get_f = run(tmp, "db", "get", "F-001", "--scope", "public")
        assert res_pub_get_f.returncode == 0
        assert "运行环境" in res_pub_get_f.stdout

    print("PASS db_selftest: all 12 SQLite DB & visibility test cases verified.")


if __name__ == "__main__":
    test_db_workflow()
