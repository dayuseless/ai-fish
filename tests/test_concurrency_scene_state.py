# -*- coding: utf-8 -*-
"""Phase 2 Test Suite: Optimistic Concurrency Control (state_revision) & 3-State Scene State Machine."""
import json
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from lib.core import MemError, load_state, save_state
from lib.scene import (
    apply_scene_patch,
    format_resume_md,
    parse_resume_md,
    push_history_snapshot,
    rollback_scene_snapshot,
)


class TestConcurrencyAndScene(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ai_fish_phase2_test_"))
        import lib.core as core_mod
        import lib.scene as scene_mod

        self.orig_state_path = core_mod.STATE_PATH
        self.orig_resume_path = scene_mod.RESUME_PATH
        self.orig_history_dir = scene_mod.HISTORY_DIR

        core_mod.STATE_PATH = self.temp_dir / "state.json"
        scene_mod.RESUME_PATH = self.temp_dir / "resume.md"
        scene_mod.HISTORY_DIR = self.temp_dir / "resume-history"

    def tearDown(self):
        import lib.core as core_mod
        import lib.scene as scene_mod

        core_mod.STATE_PATH = self.orig_state_path
        scene_mod.RESUME_PATH = self.orig_resume_path
        scene_mod.HISTORY_DIR = self.orig_history_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_state_revision_monotonic_increment(self):
        st = load_state()
        self.assertEqual(st.get("state_revision"), 0)

        st["lastNoteAt"] = "2026-11-14T10:00:00Z"
        save_state(st)
        self.assertEqual(st["state_revision"], 1)

        loaded = load_state()
        self.assertEqual(loaded["state_revision"], 1)

        save_state(loaded)
        self.assertEqual(loaded["state_revision"], 2)

    def test_state_revision_optimistic_conflict_rejection(self):
        st = load_state()
        save_state(st)  # rev is now 1

        # Process A starts with rev 1
        proc_a = load_state()
        self.assertEqual(proc_a["state_revision"], 1)

        # Process B starts with rev 1 and writes first
        proc_b = load_state()
        proc_b["lastNoteAt"] = "from B"
        save_state(proc_b, expected_revision=1)
        self.assertEqual(proc_b["state_revision"], 2)

        # Process A attempts to save expecting revision 1, but disk is now 2
        proc_a["lastNoteAt"] = "from A"
        with self.assertRaises(MemError) as ctx:
            save_state(proc_a, expected_revision=1)
        self.assertIn("乐观锁冲突", str(ctx.exception))

    def test_three_state_patch_semantics(self):
        base_scene = {
            "meta": {},
            "doing": "正在进行小猫插件测试",
            "decided": ["决定使用 MCP 架构", "决定开源"],
            "next": ["测试群聊互动", "发布版本"],
            "pending": "等待群友反馈",
        }

        # Case 1: Partial patch retaining unspecified fields (undefined)
        patch_1 = {
            "doing": "小猫插件发布完毕，转入日常维护",
            # decided is omitted -> should be retained!
            # next is omitted -> should be retained!
        }
        res_1 = apply_scene_patch(base_scene, patch_1)
        self.assertEqual(res_1["doing"], "小猫插件发布完毕，转入日常维护")
        self.assertEqual(res_1["decided"], ["决定使用 MCP 架构", "决定开源"])
        self.assertEqual(res_1["next"], ["测试群聊互动", "发布版本"])
        self.assertEqual(res_1["pending"], "等待群友反馈")

        # Case 2: Explicit clearing (null / empty string / "无")
        patch_2 = {
            "pending": "",  # Explicitly clear unresolved action/tension!
            "next": [],     # Explicitly clear next
        }
        res_2 = apply_scene_patch(res_1, patch_2)
        self.assertEqual(res_2["pending"], "")
        self.assertEqual(res_2["next"], [])
        self.assertEqual(res_2["doing"], "小猫插件发布完毕，转入日常维护")
        self.assertEqual(res_2["decided"], ["决定使用 MCP 架构", "决定开源"])

    def test_ten_step_fifo_time_machine_rollback(self):
        import lib.scene as scene_mod

        # Initial scene
        scene_mod.RESUME_PATH.write_text("SCENE_V0", encoding="utf-8")

        # Push 12 snapshots to verify 10-step FIFO prune
        for i in range(1, 13):
            push_history_snapshot(f"SCENE_V{i}", reason=f"step {i}")
            scene_mod.RESUME_PATH.write_text(f"SCENE_V{i}", encoding="utf-8")

        snaps = list(scene_mod.HISTORY_DIR.glob("resume-*.md"))
        self.assertEqual(len(snaps), 10)  # Capped at 10

        # Rollback should restore the most recent snapshot (SCENE_V12)
        ok, msg = rollback_scene_snapshot()
        self.assertTrue(ok)
        self.assertEqual(scene_mod.RESUME_PATH.read_text(encoding="utf-8").strip(), "SCENE_V12")

        # Rollback again should restore SCENE_V11
        ok, msg = rollback_scene_snapshot()
        self.assertTrue(ok)
        self.assertEqual(scene_mod.RESUME_PATH.read_text(encoding="utf-8").strip(), "SCENE_V11")


if __name__ == "__main__":
    unittest.main()
