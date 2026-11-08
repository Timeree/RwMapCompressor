"""命令行入口的端到端测试。"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rwmapcompressor.cli import default_output, main  # noqa: E402
from rwmapcompressor.tmx import TmxMap  # noqa: E402
from fixtures import build_tmx  # noqa: E402


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "map.tmx"
        self.src.write_bytes(build_tmx())

    def test_default_output_and_report(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.src)])
        self.assertEqual(code, 0)
        target = default_output(self.src)
        self.assertTrue(target.is_file())
        self.assertIn("《压缩结果》", stdout.getvalue())
        self.assertIn("体积减少", stdout.getvalue())
        self.assertEqual(TmxMap.from_file(target).used_gids,
                         {1, 2, 3, 4, 17, 18, 33, 34})

    def test_explicit_output_and_switches(self):
        target = Path(self.tmp.name) / "custom.tmx"
        with contextlib.redirect_stdout(io.StringIO()):
            code = main([str(self.src), "-o", str(target), "--ignore-units",
                         "--minify-xml", "--obfuscate", "--seed", "4"])
        self.assertEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertNotIn(b"<!--", target.read_bytes())
        result = TmxMap.from_file(target)
        self.assertEqual(len(result.layers), 3)
        self.assertTrue(all(len(layer.gids) == 64 for layer in result.layers))

    def test_minify_xml_flag(self):
        plain = Path(self.tmp.name) / "plain.tmx"
        compact = Path(self.tmp.name) / "compact.tmx"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.src), "-o", str(plain)]), 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.src), "-o", str(compact),
                                   "--minify-xml"]), 0)
        self.assertLess(compact.stat().st_size, plain.stat().st_size)
        self.assertEqual([layer.gids[:] for layer in TmxMap.from_file(compact).layers],
                         [layer.gids[:] for layer in TmxMap.from_file(plain).layers])

    def test_rotate_switch_no_longer_exists(self):
        """主动旋转功能已移除，旧开关应被拒绝。"""
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main([str(self.src), "--rotate"])

    def test_missing_input(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                main([str(Path(self.tmp.name) / "nope.tmx")])
        self.assertIn("输入文件不存在", stderr.getvalue())

    def test_same_input_output_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main([str(self.src), "-o", str(self.src)])

    def test_invalid_map_returns_1(self):
        broken = Path(self.tmp.name) / "broken.tmx"
        broken.write_bytes(b"<not-a-map/>")
        with contextlib.redirect_stderr(io.StringIO()):
            code = main([str(broken)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
