"""chunkshare —— 自检测试。

检查同一文档不同分片之间的描述是否一致

覆盖：正常路径、边界输入、防呆红线、幂等性。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chunkshare  # noqa: E402

SAMPLE_TEXT = '系统必须返回结果。\n系统不得返回结果。'


class TestChunkshare(unittest.TestCase):
    """长文档分片一致性"""

    def test_cli_help_exits_zero(self):
        """--help 必须能正常退出。"""
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "chunkshare.py"), "--help"],
            capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0)

    def test_cli_rejects_empty_input(self):
        """空输入必须明确报错，不能静默成功。"""
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "chunkshare.py"), "--text", "   "],
            capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(proc.returncode, 0)

    def test_cli_json_output_parses(self):
        """--json 输出必须是合法 JSON。"""
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "chunkshare.py"), "--text", SAMPLE_TEXT,
             "--json"],
            capture_output=True, text=True, encoding="utf-8")
        if proc.returncode not in (0, 1):
            self.fail(f"退出码异常：{proc.returncode} {proc.stderr[:300]}")
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, dict)

    def test_does_not_mutate_input(self):
        """防呆：分析过程不得改动调用方传入的对象。"""
        payload = SAMPLE_TEXT
        before = payload
        chunkshare.chunkshare_analyze(payload)
        self.assertEqual(before, payload)

    def test_is_idempotent(self):
        """同一输入跑两次结果必须一致。"""
        a = chunkshare.chunkshare_analyze(SAMPLE_TEXT)
        b = chunkshare.chunkshare_analyze(SAMPLE_TEXT)
        self.assertEqual(json.dumps(a, ensure_ascii=False, sort_keys=True),
                         json.dumps(b, ensure_ascii=False, sort_keys=True))

    def test_detects_opposite_claims(self):
        r = chunkshare.chunkshare_analyze(SAMPLE_TEXT)
        self.assertGreaterEqual(r["conflict_count"], 1)
        for p in r["pairs"]:
            self.assertIn("a", p)
            self.assertIn("b", p)
            self.assertNotEqual(p["a"]["polarity"], p["b"]["polarity"])

    def test_does_not_invent_conflicts(self):
        """防呆：同向的两句话不算矛盾。"""
        r = chunkshare.chunkshare_analyze("系统必须返回结果。\n系统应当返回结果。")
        self.assertEqual(r["conflict_count"], 0)
