"""压缩流水线、旋转图块保留修复与三个开关的回归测试。"""

from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from rwmapcompressor.atlas import Atlas, Grid  # noqa: E402
from rwmapcompressor.core import Options, compress  # noqa: E402
from rwmapcompressor.tmx import FLAG_MASK, GID_MASK, TmxMap  # noqa: E402
from fixtures import build_tmx  # noqa: E402


def atlas_image(tmx: TmxMap, index: int) -> Image.Image:
    prop = tmx.tilesets[index].embedded_png
    raw = base64.b64decode("".join((prop.text or "").split()))
    image = Image.open(io.BytesIO(raw))
    image.load()
    return image.convert("RGBA")


def tile_pixel(image: Image.Image, local_id: int) -> tuple[int, int, int, int]:
    x, y = (local_id % 4) * 8 + 4, (local_id // 4) * 8 + 4
    return image.getpixel((x, y))


class CompressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / "map.tmx"
        self.dst = Path(self.tmp.name) / "out.tmx"
        self.src.write_bytes(build_tmx())

    def run_compress(self, options: Options | None = None):
        stats = compress(self.src, self.dst, options)
        return stats, TmxMap.from_file(self.dst)

    def test_unused_tiles_cleared_used_tiles_intact(self):
        stats, result = self.run_compress()
        ground = atlas_image(result, 0)
        for local in range(4):
            self.assertEqual(tile_pixel(ground, local)[3], 255,
                             f"使用中的图块 {local} 不应被擦除")
        for local in range(4, 16):
            self.assertEqual(tile_pixel(ground, local)[3], 0,
                             f"未使用的图块 {local} 应被擦成透明")
        self.assertEqual(result.used_gids, {1, 2, 3, 4, 17, 18, 33, 34})
        self.assertGreater(stats.saved_bytes, 0)
        self.assertEqual(stats.atlas_count, 3)
        self.assertGreater(stats.removed_tile_nodes, 0)

    def test_rotated_gids_are_kept_by_default(self):
        """核心修复：旧版把带标志的 GID 当负数忽略，导致对应贴图被误抹。

        这是默认行为（无开关）：压缩后旋转图块的贴图仍在，标志位仍在，
        且不会凭空给任何图块新增旋转标志。
        """
        self.src.write_bytes(build_tmx(flipped=True))
        stats, result = self.run_compress()
        self.assertEqual(stats.flipped_cells, 3)
        ground = atlas_image(result, 0)
        for local in (0, 2, 3):  # gid 1 / 3 / 4 带水平翻转标志
            self.assertEqual(tile_pixel(ground, local)[3], 255)
        flipped = sum(1 for layer in result.layers
                      for gid in layer.gids if gid & FLAG_MASK)
        self.assertEqual(flipped, 3, "原有旋转标志必须原样保留，且不新增")
        original = TmxMap.from_bytes(build_tmx(flipped=True))
        self.assertEqual([g & FLAG_MASK for g in result.layers[0].gids],
                         [g & FLAG_MASK for g in original.layers[0].gids])

    def test_no_rotation_is_added_to_plain_maps(self):
        """没有旋转图块的地图，压缩后也不该出现任何旋转标志。"""
        self.src.write_bytes(build_tmx(flipped=False))
        stats, result = self.run_compress()
        self.assertEqual(stats.flipped_cells, 0)
        self.assertFalse(any(g & FLAG_MASK for layer in result.layers
                             for g in layer.gids))

    def test_rotated_gids_survive_obfuscate(self):
        """混淆会改写 GID，但旋转标志必须原样跟着保留。"""
        self.src.write_bytes(build_tmx(flipped=True))
        stats, result = self.run_compress(Options(obfuscate=True, seed=8))
        self.assertEqual(stats.flipped_cells, 3)
        self.assertEqual(sum(1 for layer in result.layers
                             for gid in layer.gids if gid & FLAG_MASK), 3)

    def test_unused_tile_nodes_removed_but_used_kept(self):
        _stats, result = self.run_compress()
        # ground tileset 只有 id 0/1 两个 <tile> 定义，二者都在使用中。
        self.assertEqual(set(result.tilesets[0].tile_nodes), {0, 1})
        water = result.tilesets[0].tile_nodes[0].find("properties/property")
        self.assertEqual(water.get("name"), "water")

    def test_ignore_units(self):
        stats, result = self.run_compress(Options(ignore_units=True))
        units = atlas_image(result, 2)
        self.assertTrue(all(tile_pixel(units, i)[3] == 0 for i in range(16)),
                        "Units 图集应被整张清空")
        self.assertEqual(stats.kept_tiles, 6)  # ground 4 + items 2

        # 但单位定义（team / unit 属性）必须保留，否则游戏里单位会消失
        nodes = result.tilesets[2].tile_nodes
        self.assertEqual(set(nodes), {0, 1})
        props = {p.get("name") for p in nodes[0].findall("properties/property")}
        self.assertEqual(props, {"team", "unit"})
        unit_layer = [layer for layer in result.layers if layer.name == "Units"][0]
        self.assertEqual({g & GID_MASK for g in unit_layer.gids if g}, {33, 34})

    def test_obfuscate_remaps_gids_and_is_deterministic(self):
        stats, result = self.run_compress(Options(obfuscate=True, seed=11))
        self.assertGreater(stats.remapped_gids, 0)
        # 混淆改变的是「哪个 GID 指向哪张图块」，逐格序列必须不同。
        original = TmxMap.from_bytes(build_tmx())
        self.assertNotEqual(
            [g & GID_MASK for g in result.layers[0].gids],
            [g & GID_MASK for g in original.layers[0].gids],
        )
        # 保留的图块被紧凑排到图集头部，其余透明
        ground = atlas_image(result, 0)
        occupied = [i for i in range(16) if tile_pixel(ground, i)[3] == 255]
        self.assertEqual(occupied, list(range(4)))
        # <tile> 的 id 与图层引用的 GID 保持一致
        referenced = {g & GID_MASK for g in result.layers[0].gids if g} - {17, 18}
        self.assertTrue(referenced)
        for ts in result.tilesets:
            for local_id in ts.tile_nodes:
                self.assertIn(ts.first_gid + local_id, result.used_gids)

        second = Path(self.tmp.name) / "out2.tmx"
        compress(self.src, second, Options(obfuscate=True, seed=11))
        self.assertEqual(self.dst.read_bytes(), second.read_bytes())
        third = Path(self.tmp.name) / "out3.tmx"
        compress(self.src, third, Options(obfuscate=True, seed=12))
        self.assertNotEqual(self.dst.read_bytes(), third.read_bytes())

    def test_minify_xml_reduces_size_without_touching_data(self):
        self.src.write_bytes(build_tmx(with_comment=True))
        plain = Path(self.tmp.name) / "plain.tmx"
        stats_plain = compress(self.src, plain)
        stats_min, result = self.run_compress(Options(minify_xml=True))
        self.assertGreater(stats_min.xml_saved_bytes, 0)
        self.assertLess(stats_min.output_size, stats_plain.output_size)
        self.assertNotIn(b"<!--", self.dst.read_bytes())
        baseline = TmxMap.from_file(plain)
        self.assertEqual([layer.gids[:] for layer in result.layers],
                         [layer.gids[:] for layer in baseline.layers])
        self.assertEqual(result.used_gids, baseline.used_gids)
        # 内嵌 PNG 的 base64 内容逐个一致
        for a, b in zip(result.tilesets, baseline.tilesets):
            self.assertEqual(a.embedded_png.text, b.embedded_png.text)

    def test_minify_xml_lossless_across_layer_encodings(self):
        for encoding, compression in (("base64", "gzip"), ("base64", "zlib"),
                                     ("base64", None), ("csv", None),
                                     ("xml", None)):
            with self.subTest(encoding=encoding, compression=compression):
                self.src.write_bytes(build_tmx(ground=encoding,
                                               ground_comp=compression))
                expected = TmxMap.from_file(self.src)
                _stats, result = self.run_compress(Options(minify_xml=True))
                self.assertEqual([layer.gids[:] for layer in result.layers],
                                 [layer.gids[:] for layer in expected.layers])
                for layer in result.layers:
                    self.assertEqual(len(layer.gids), 64)

    def test_all_three_switches_combined(self):
        self.src.write_bytes(build_tmx(with_comment=True))
        stats, result = self.run_compress(
            Options(ignore_units=True, obfuscate=True, minify_xml=True, seed=5))
        self.assertGreater(stats.remapped_gids, 0)
        self.assertGreater(stats.xml_saved_bytes, 0)
        self.assertEqual(stats.kept_tiles, 6)  # 忽略 Units 后只剩 6 个
        self.assertNotIn(b"<!--", self.dst.read_bytes())
        self.assertEqual(len(result.layers), 3)
        for layer in result.layers:
            self.assertEqual(len(layer.gids), 64)

    def test_default_options_have_no_side_effects(self):
        """不带任何开关时，XML 结构保持原样（不压缩、不新增标志）。"""
        raw = build_tmx(with_comment=True)
        self.src.write_bytes(raw)
        stats, _result = self.run_compress()
        self.assertEqual(stats.xml_saved_bytes, 0)
        self.assertIn(b"<!--", self.dst.read_bytes())

    def test_all_layer_encodings(self):
        for encoding, compression in (("base64", "gzip"), ("base64", "zlib"),
                                     ("base64", None), ("csv", None),
                                     ("xml", None)):
            with self.subTest(encoding=encoding, compression=compression):
                self.src.write_bytes(build_tmx(ground=encoding,
                                               ground_comp=compression))
                _stats, result = self.run_compress()
                self.assertEqual(len(result.layers[0].gids), 64)
                self.assertEqual(result.used_gids,
                                 {1, 2, 3, 4, 17, 18, 33, 34})

    def test_output_reparseable_and_layer_sizes_intact(self):
        _stats, result = self.run_compress()
        self.assertEqual((result.width, result.height), (8, 8))
        for layer in result.layers:
            self.assertEqual(len(layer.gids), 64)

    def test_options_expose_exactly_three_switches(self):
        self.assertEqual(
            {name for name, value in vars(Options()).items()
             if isinstance(value, bool)},
            {"ignore_units", "obfuscate", "minify_xml"},
        )


class AtlasTest(unittest.TestCase):
    def test_relocate_moves_pixels_exactly(self):
        prop = ET.Element("property", {"name": "embedded_png"})
        raw = build_tmx()
        tmx = TmxMap.from_bytes(raw)
        source_prop = tmx.tilesets[0].embedded_png
        prop.text = source_prop.text
        atlas = Atlas.load(prop)
        grid = Grid.for_tileset(tmx.tilesets[0], atlas.image.size)
        original = atlas.image.copy()
        keep = {0, 1, 2, 3}
        mapping = atlas.rebuild(grid, keep, shuffle=True, seed=99,
                                scramble=False)
        self.assertEqual(set(mapping), keep)
        self.assertEqual(set(mapping.values()), set(range(4)))
        for old, new in mapping.items():
            self.assertEqual(tile_pixel(atlas.image, new),
                             tile_pixel(original, old))
        for empty in range(4, 16):
            self.assertEqual(tile_pixel(atlas.image, empty)[3], 0)


if __name__ == "__main__":
    unittest.main()
