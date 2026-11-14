#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test suite for Phase 1: Ingress/Egress ACL Gates, Fail-Closed, and Visibility Scoping."""
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


def test_acl_security():
    with tempfile.TemporaryDirectory(prefix="ai-fish-acl-test-") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "ai-fish" / "daily" / "raw").mkdir(parents=True)
        (tmp / "ai-fish" / "index").mkdir(parents=True)
        (tmp / "ai-fish" / "snapshots").mkdir(parents=True)
        shutil.copytree(MEM_SRC.parent, tmp / "ai-fish" / "bin", dirs_exist_ok=True)

        # Mock canonical rules and seal
        can_dir = tmp / "canonical"
        can_dir.mkdir(parents=True)
        rules_bytes = b"# Rules\n"
        can_rules = can_dir / "RULES.md"
        can_rules.write_bytes(rules_bytes)
        digest = hashlib.sha256(rules_bytes).hexdigest()
        (can_dir / "RULES.sha256").write_bytes(digest.encode("utf-8"))

        (tmp / "ai-fish" / "RULES.md").write_bytes(rules_bytes)
        (tmp / "ai-fish" / "index" / "rules.sha256").write_text(f"{digest}  RULES.md\n", encoding="utf-8")

        cfg = {
            "version": 1,
            "workspace": str(tmp),
            "canonical_rules": str(can_rules),
            "canonical_seal": str(can_dir / "RULES.sha256"),
            "max_note_chars": 12000,
            "max_search_results": 50,
        }
        (tmp / "ai-fish" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (tmp / "ai-fish" / "state.json").write_text(json.dumps({}), encoding="utf-8")

        # Long term files
        (tmp / "ai-fish" / "SELF.md").write_text("# SELF.md\n- **F-001｜运行环境**：公开环境事实。\n", encoding="utf-8")
        (tmp / "ai-fish" / "USER.md").write_text("# USER.md\n- **U-001｜密码与银行卡**：管理员银行卡6222。\n", encoding="utf-8")
        (tmp / "ai-fish" / "MEMORY.md").write_text("# MEMORY.md\n- **M-001｜秘密项目**：绝密计划X。\n", encoding="utf-8")
        (tmp / "ai-fish" / "SPEC.md").write_text("# SPEC.md\n", encoding="utf-8")
        (tmp / "ai-fish" / "META.md").write_text("# META.md\n", encoding="utf-8")

        # 1. Test Ingress Guard: Scope Escalation Protection
        # Agent attempts to create public inference -> must be downgraded to admin_only
        res = run(tmp, "note", "--kind", "inference", "--text", "智能体推测用户喜欢猫", "--actor", "agent", "--visibility", "public")
        assert res.returncode == 0
        
        # User creates public statement -> allowed
        res = run(tmp, "note", "--kind", "statement", "--text", "用户公开说欢迎大家来玩", "--actor", "user", "--visibility", "public")
        assert res.returncode == 0

        # Normal admin_only secret
        res = run(tmp, "note", "--kind", "event", "--text", "用户私聊秘密讨论核心机密42", "--actor", "user", "--visibility", "admin_only")
        assert res.returncode == 0

        # Sync DB
        res = run(tmp, "db", "sync")
        assert res.returncode == 0

        # 2. Test Fail-Closed Egress in search_fts:
        # A. Admin can find both secrets and public info
        res = run(tmp, "search", "--query", "核心机密42", "--scope", "admin")
        assert res.returncode == 0
        assert "核心机密42" in res.stdout

        # B. Public scope CANNOT find admin_only secrets
        # B. Public scope CANNOT find admin_only secrets (0 hits)
        res = run(tmp, "search", "--query", "核心机密42", "--scope", "public")
        assert res.returncode == 0
        assert "0 hit(s)" in res.stdout or "NO_MATCHES" in res.stdout
        # Content snippet should not appear in search results body
        content_lines = [l for l in res.stdout.splitlines() if not l.startswith("SEARCH ")]
        assert not any("核心机密42" in l for l in content_lines)
        assert "0 hit(s)" in res.stdout or "NO_MATCHES" in res.stdout

        # C. Public scope CAN find public statement
        res = run(tmp, "search", "--query", "欢迎大家来玩", "--scope", "public")
        assert res.returncode == 0
        assert "欢迎大家来玩" in res.stdout

        # D. Ingress guard downgraded agent inference from public -> cannot be found by public
        res = run(tmp, "search", "--query", "推测用户喜欢猫", "--scope", "public")
        assert res.returncode == 0
        content_lines = [l for l in res.stdout.splitlines() if not l.startswith("SEARCH ")]
        assert not any("推测用户喜欢猫" in l for l in content_lines)

        # E. Verify Fail-Closed with direct db get / query
        sys.path.insert(0, str(tmp / "ai-fish" / "bin"))
        from lib.db import get_long_term_item, search_fts, query_raw_events

        # search_fts with unknown scope -> Fail-Closed to public only
        fts_res_unknown = search_fts("核心机密42", scope="unauthorized_guest", base=tmp / "ai-fish")
        assert len(fts_res_unknown) == 0, f"Fail-Closed failed! Got: {fts_res_unknown}"

        fts_res_admin = search_fts("核心机密42", scope="admin", base=tmp / "ai-fish")
        assert len(fts_res_admin) > 0, "Admin should see secret"
        assert "visibility" in fts_res_admin[0], "visibility must be returned in search_fts"
        assert fts_res_admin[0]["visibility"] == "admin_only"

        # get_long_term_item with unknown scope -> Fail-Closed
        lt_sec = get_long_term_item("U-001", scope="guest", base=tmp / "ai-fish")
        assert lt_sec is None, "Guest must not access U-001 private item!"

        lt_admin = get_long_term_item("U-001", scope="admin", base=tmp / "ai-fish")
        assert lt_admin is not None, "Admin should access U-001"
        assert lt_admin["visibility"] == "admin_only"

        # query_raw_events with unknown scope -> Fail-Closed
        evts_sec = query_raw_events(scope="unknown", base=tmp / "ai-fish")
        for ev in evts_sec:
            assert ev["visibility"] == "public", f"Non-admin query leaked non-public event: {ev}"

        # 3. Test Fail-Closed in Text-only fallback search:
        # Deliberately unlink DB to test pure-text fallback
        (tmp / "ai-fish" / "index" / "memory.db").unlink()

        res_txt_pub = run(tmp, "search", "--query", "核心机密42", "--scope", "public", "--text-only")
        assert res_txt_pub.returncode == 0
        content_lines_txt = [l for l in res_txt_pub.stdout.splitlines() if not l.startswith("SEARCH ")]
        assert not any("核心机密42" in l for l in content_lines_txt)

        res_txt_admin = run(tmp, "search", "--query", "核心机密42", "--scope", "admin", "--text-only")
        assert res_txt_admin.returncode == 0
        assert "核心机密42" in res_txt_admin.stdout

    print("PASS test_acl_ingress_egress: all Ingress/Egress ACL gates and Fail-Closed tests verified.")


if __name__ == "__main__":
    test_acl_security()
