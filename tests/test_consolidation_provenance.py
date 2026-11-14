# -*- coding: utf-8 -*-
"""Phase 3 Test Suite: Consolidation Pre-flight Gate, Atomic Transaction Rollback, & Bidirectional Provenance."""
import json
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from lib.core import MemError
from lib.db import get_db, get_long_term_item, init_db, query_raw_events
from lib.promote import consolidate_events


class TestConsolidationProvenance(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ai_fish_phase3_test_"))
        import lib.db as db_mod
        self.orig_db_base = db_mod.BASE
        db_mod.BASE = self.temp_dir

        self.conn = get_db(self.temp_dir, write=True)
        init_db(self.conn)

        # Seed 3 test raw events
        self.conn.execute("""
        INSERT INTO raw_events (id, ts, date, kind, actor, text, ref, tags, is_pending, visibility)
        VALUES 
        ('evt-20261114-100001-aaaa', '2026-11-14T10:00:01Z', '2026-11-14', 'event', 'admin', '小猫完成了猫砂盆训练', '', '', 0, 'admin_only'),
        ('evt-20261114-100002-bbbb', '2026-11-14T10:00:02Z', '2026-11-14', 'event', 'admin', '小猫学会了用爪子拨动逗猫棒', '', '', 0, 'admin_only'),
        ('evt-20261114-100003-cccc', '2026-11-14T10:00:03Z', '2026-11-14', 'statement', 'user', '小猫公开亮相', '', '', 0, 'public')
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        import lib.db as db_mod
        db_mod.BASE = self.orig_db_base
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_preflight_schema_validation(self):
        # Missing title & content
        with self.assertRaises(MemError) as ctx:
            consolidate_events(["evt-20261114-100001-aaaa"], {"key": "M-999"}, base=self.temp_dir)
        self.assertIn("Schema 校验不通过", str(ctx.exception))

        # Empty event list
        with self.assertRaises(MemError) as ctx:
            consolidate_events([], {"key": "M-999", "title": "T", "content": "C"}, base=self.temp_dir)
        self.assertIn("事件列表为空", str(ctx.exception))

    def test_preflight_acl_escalation_guard(self):
        # Trying to consolidate private events into a public long-term memory must be blocked!
        summary = {
            "key": "M-100",
            "title": "小猫技能概括",
            "content": "小猫已掌握基础生活与娱乐技能",
            "visibility": "public",  # Escalation attempt!
        }
        with self.assertRaises(MemError) as ctx:
            consolidate_events(["evt-20261114-100001-aaaa", "evt-20261114-100002-bbbb"], summary, base=self.temp_dir)
        self.assertIn("不可提权升格为 public", str(ctx.exception))

        # Check that no partial data was inserted
        lt = get_long_term_item("M-100", scope="admin", base=self.temp_dir)
        self.assertIsNone(lt)

    def test_preflight_missing_events_rejection(self):
        summary = {
            "key": "M-101",
            "title": "概括",
            "content": "内容",
            "visibility": "admin_only",
        }
        with self.assertRaises(MemError) as ctx:
            consolidate_events(["evt-nonexistent-1234"], summary, base=self.temp_dir)
        self.assertIn("找不到源事件", str(ctx.exception))

    def test_bidirectional_provenance_and_atomic_commit(self):
        event_ids = ["evt-20261114-100001-aaaa", "evt-20261114-100002-bbbb"]
        summary = {
            "key": "M-102",
            "title": "小猫初步适应期总结",
            "content": "小猫已完全适应室内环境并学会基础生活习惯。",
            "doc": "MEMORY.md",
            "section": "小猫陪伴",
            "visibility": "admin_only",
        }
        res = consolidate_events(event_ids, summary, base=self.temp_dir)
        self.assertTrue(res["success"])
        item_id = res["item_id"]
        self.assertEqual(res["consolidated_from"], event_ids)

        # 1. Check long-term memory consolidated_from
        lt = get_long_term_item("M-102", scope="admin", base=self.temp_dir)
        self.assertIsNotNone(lt)
        self.assertEqual(json.loads(lt["consolidated_from"]), event_ids)

        # 2. Check raw events superseded_by
        events = query_raw_events(base=self.temp_dir, limit=10)
        ev_map = {e["id"]: e for e in events}
        self.assertEqual(ev_map["evt-20261114-100001-aaaa"]["superseded_by"], item_id)
        self.assertEqual(ev_map["evt-20261114-100002-bbbb"]["superseded_by"], item_id)
        # Untouched event should remain empty
        self.assertEqual(ev_map["evt-20261114-100003-cccc"]["superseded_by"], "")


if __name__ == "__main__":
    unittest.main()
