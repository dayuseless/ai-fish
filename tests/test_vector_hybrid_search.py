# -*- coding: utf-8 -*-
"""Phase 4.1 Test Suite: 256-Dim Local Dense Vectorizer & Hybrid Retrieval Fusion."""
import math
import shutil
import sys
import tempfile
from pathlib import Path
import unittest

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

from lib.db import get_db, init_db, search_dense, search_hybrid
from lib.vector import (
    LOCAL_VECTOR_DIM,
    cosine_similarity,
    fnv1a_32,
    generate_local_embedding,
)


class TestVectorAndHybridSearch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ai_fish_phase4_test_"))
        import lib.db as db_mod
        self.orig_db_base = db_mod.BASE
        db_mod.BASE = self.temp_dir

        self.conn = get_db(self.temp_dir, write=True)
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        import lib.db as db_mod
        db_mod.BASE = self.orig_db_base
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vector_properties(self):
        text = "小猫陪伴插件与MCP工具服务"
        vec = generate_local_embedding(text)

        # 1. Dimension check
        self.assertEqual(len(vec), LOCAL_VECTOR_DIM)
        self.assertEqual(LOCAL_VECTOR_DIM, 256)

        # 2. L2 Norm check (unit length)
        norm = math.sqrt(sum(x * x for x in vec))
        self.assertAlmostEqual(norm, 1.0, places=4)

        # 3. Determinism check
        vec2 = generate_local_embedding(text)
        self.assertEqual(vec, vec2)

    def test_semantic_cosine_similarity(self):
        # Exact match
        v1 = generate_local_embedding("猫咪训练与逗猫棒")
        v2 = generate_local_embedding("猫咪训练与逗猫棒")
        sim_exact = cosine_similarity(v1, v2)
        self.assertAlmostEqual(sim_exact, 1.0, places=4)

        # High similarity (semantically & character related)
        v_related = generate_local_embedding("小猫咪日常训练与玩具逗猫棒")
        sim_high = cosine_similarity(v1, v_related)
        self.assertGreater(sim_high, 0.40)

        # Low similarity (unrelated domain)
        v_unrelated = generate_local_embedding("量子物理量子力学拓扑绝缘体超导实验")
        sim_low = cosine_similarity(v1, v_unrelated)
        self.assertLess(sim_low, 0.25)
        self.assertGreater(sim_high, sim_low)

    def test_hybrid_search_fusion(self):
        # Insert long term item
        self.conn.execute("""
        INSERT INTO long_term_items (id, item_key, doc, section, title, content, visibility, synced_at)
        VALUES 
        ('lt-kitten', 'K-001', 'MEMORY.md', '小猫', '小猫生活习性', '小猫非常喜欢玩毛线球和逗猫棒，日常在室内活动', 'public', '2026-11-14T10:00:00Z'),
        ('lt-quantum', 'Q-001', 'MEMORY.md', '科研', '量子力学与超导', '超导材料的零电阻效应与迈斯纳效应实验研究', 'public', '2026-11-14T10:00:00Z')
        """)
        self.conn.commit()

        # Dense vector search across long term items with cosine similarity
        hits = search_dense("逗猫棒玩具", limit=5, scope="public", threshold=0.15, base=self.temp_dir)
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]["item_id"], "K-001")
        self.assertIn("similarity", hits[0])
        self.assertGreater(hits[0]["similarity"], 0.15)


if __name__ == "__main__":
    unittest.main()
