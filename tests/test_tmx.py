"""TMX 编解码与 GID 标志的单元测试。"""

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rwmapcompressor.tmx import (  # noqa: E402
    FLAG_MASK, FLIP_D, FLIP_H, FLIP_V, GID_MASK, ROT_HEX120,
    TmxError, TmxMap, decode_gids, encode_gids, join_gid, split_gid,
)
from fixtures import build_tmx  # noqa: E402


class GidFlagsTest(unittest.TestCase):
    def test_split_and_join(self):
        raw = FLIP_H | FLIP_D | 42
        base, flags = split_gid(raw)
        self.assertEqual(base, 42)
        self.assertEqual(flags, FLIP_H | FLIP_D)
        self.assertEqual(join_gid(base, flags), raw)

    def test_all_four_flags_are_cleared(self):
        flags = FLIP_H | FLIP_V | FLIP_D | ROT_HEX120
        self.assertEqual(split_gid(flags | 7)[0], 7)
        self.assertEqual(GID_MASK, 0x0FFFFFFF)
        self.assertEqual(FLAG_MASK, 0xF0000000)

    def test_rotation_flags_are_distinct(self):
        from rwmapcompressor.tmx import ROTATION_FLAGS
        self.assertEqual(len(set(ROTATION_FLAGS.values())), 4)


class LayerCodecTest(unittest.TestCase):
    GIDS = list(range(1, 25)) + [0x80000000 | 3, 0]

    def _roundtrip(self, encoding: str | None, compression: str | None):
        attrs = ""
        if encoding:
            attrs += f' encoding="{encoding}"'
        if compression:
            attrs += f' compression="{compression}"'
        data = ET.fromstring(f"<data{attrs}/>")
        encode_gids(data, self.GIDS, width=8)
        self.assertEqual(decode_gids(data), self.GIDS)

    def test_base64_gzip(self):
        self._roundtrip("base64", "gzip")

    def test_base64_zlib(self):
        self._roundtrip("base64", "zlib")

    def test_base64_uncompressed(self):
        self._roundtrip("base64", None)

    def test_csv(self):
        self._roundtrip("csv", None)

    def test_xml_tiles(self):
        self._roundtrip(None, None)

    def test_csv_multiline_does_not_merge_numbers(self):
        """回归：行尾与下一行行首的数字不能被粘成一个数。"""
        data = ET.fromstring('<data encoding="csv"/>')
        encode_gids(data, list(range(1, 65)), width=8)
        self.assertIn("\n", data.text)
        self.assertEqual(len(decode_gids(data)), 64)
        self.assertEqual(decode_gids(data)[7:9], [8, 9])

    def test_csv_original_tiled_style(self):
        data = ET.fromstring('<data encoding="csv">1,2,3,\n4,5,6,\n</data>')
        self.assertEqual(decode_gids(data), [1, 2, 3, 4, 5, 6])

    def test_unsupported_encoding(self):
        data = ET.fromstring('<data encoding="xml">1</data>')
        with self.assertRaises(TmxError):
            decode_gids(data)

    def test_broken_base64_length(self):
        import base64
        data = ET.fromstring(
            f'<data encoding="base64">{base64.b64encode(b"abc").decode()}</data>'
        )
        with self.assertRaises(TmxError):
            decode_gids(data)


class MapModelTest(unittest.TestCase):
    def test_layers_and_tilesets(self):
        tmx = TmxMap.from_bytes(build_tmx())
        self.assertEqual((tmx.width, tmx.height), (8, 8))
        self.assertEqual([layer.name for layer in tmx.layers],
                         ["Ground", "Items", "Units"])
        self.assertEqual([layer.name for layer in tmx.unit_layers()], ["Units"])
        self.assertEqual(len(tmx.tilesets), 3)

    def test_used_gids_strip_flags(self):
        tmx = TmxMap.from_bytes(build_tmx(flipped=True))
        self.assertEqual(tmx.used_gids, {1, 2, 3, 4, 17, 18, 33, 34})

    def test_tileset_ownership_uses_largest_firstgid(self):
        tmx = TmxMap.from_bytes(build_tmx())
        for gid, first in ((1, 1), (16, 1), (17, 17), (32, 17),
                           (33, 33), (48, 33)):
            self.assertEqual(tmx.tileset_for(gid).first_gid, first)
        self.assertIsNone(tmx.tileset_for(0))
        self.assertIsNone(tmx.tileset_for(49))

    def test_embedded_png_and_tile_properties_survive_parse(self):
        tmx = TmxMap.from_bytes(build_tmx())
        for tileset in tmx.tilesets:
            self.assertIsNotNone(tileset.embedded_png)
            self.assertIsNotNone(tileset.image_source)
        unit_props = tmx.tilesets[2].tile_nodes[0].find("properties/property")
        self.assertEqual(unit_props.get("name"), "team")

    def test_remap_preserves_flags(self):
        tmx = TmxMap.from_bytes(build_tmx(flipped=True))
        ground = tmx.layers[0]
        before = [g & FLAG_MASK for g in ground.gids]
        tmx.remap({1: 9, 3: 11})
        after = [g & FLAG_MASK for g in ground.gids]
        self.assertEqual(before, after)
        self.assertEqual({g & GID_MASK for g in ground.gids if g},
                         {9, 2, 11, 4})

    def test_apply_flags_keeps_base_gid(self):
        tmx = TmxMap.from_bytes(build_tmx(flipped=False))
        ground = tmx.layers[0]
        before = [g & GID_MASK for g in ground.gids]
        changed = ground.apply_flags(lambda _base: FLIP_H)
        self.assertEqual(changed, 17)
        self.assertEqual([g & GID_MASK for g in ground.gids], before)
        self.assertTrue(all(g & FLIP_H for g in ground.gids if g))

    def test_to_bytes_is_reparseable(self):
        tmx = TmxMap.from_bytes(build_tmx())
        again = TmxMap.from_bytes(tmx.to_bytes())
        self.assertEqual(again.used_gids, tmx.used_gids)

    def test_bad_cell_count_rejected(self):
        raw = build_tmx().replace(
            b'<layer name="Ground" width="8" height="8">',
            b'<layer name="Ground" width="9" height="8">', 1)
        with self.assertRaises(TmxError):
            TmxMap.from_bytes(raw)


if __name__ == "__main__":
    unittest.main()
