#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟数据问数分析示例（tools/mock_qa_demo.py）的端到端测试。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from _support import PACK_DIR, Capture

DEMO_PATH = PACK_DIR / "tools" / "mock_qa_demo.py"


def load_demo_module():
    spec = importlib.util.spec_from_file_location("mock_qa_demo", DEMO_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class MockQaDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.demo = load_demo_module()

    def test_samples_cover_all_26_interfaces(self) -> None:
        with Capture() as capture:
            code = self.demo.main(["--samples"])
        self.assertEqual(code, 0)
        out = capture.stdout.getvalue()
        self.assertIn("26 / 26 个接口返回成功", out)
        self.assertIn("DF-2026-0001", out)
        self.assertIn("query_station_scale_analysis", out)

    def test_full_demo_runs_end_to_end(self) -> None:
        with Capture() as capture:
            code = self.demo.main([])
        self.assertEqual(code, 0)
        out = capture.stdout.getvalue()
        self.assertIn("完成：12 个问题全部通过接口取数 + 分析引擎计算", out)
        self.assertIn("健康分 86.3", out)
        self.assertIn("DIAG-BUSHING-MOISTURE", out)
        self.assertIn("设备画像报告", out)
        self.assertIn("重复缺陷簇 0 个", out)


if __name__ == "__main__":
    unittest.main()
