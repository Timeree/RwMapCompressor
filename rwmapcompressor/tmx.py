"""TMX（Tiled XML）地图的读取、图层数据编解码与 GID 标志处理。

Rusted Warfare 的地图是 Tiled 的 ``.tmx`` 文件：每个 ``<layer>`` 的 ``<data>``
是一串小端 uint32 的 Global Tile ID。最高的 4 个 bit 不是 ID 的一部分，而是
翻转 / 旋转标志，解析后必须先清除才能定位到 tileset 里的图块。

参考：https://doc.mapeditor.org/en/stable/reference/global-tile-ids/
"""

from __future__ import annotations

import base64
import gzip
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

__all__ = [
    "FLIP_H",
    "FLIP_V",
    "FLIP_D",
    "ROT_HEX120",
    "FLAG_MASK",
    "GID_MASK",
    "ROTATION_FLAGS",
    "TmxError",
    "split_gid",
    "join_gid",
    "Layer",
    "Tileset",
    "TmxMap",
]

# --- GID 标志位 -----------------------------------------------------------

FLIP_H = 0x80000000        # 水平翻转
FLIP_V = 0x40000000        # 垂直翻转
FLIP_D = 0x20000000        # 对角翻转（配合 H/V 实现 90 度旋转）
ROT_HEX120 = 0x10000000    # 六边形地图 120 度旋转；普通地图也必须清除
FLAG_MASK = FLIP_H | FLIP_V | FLIP_D | ROT_HEX120
GID_MASK = 0x0FFFFFFF

# Tiled 的 90 度旋转 = 先对角翻转，再水平 / 垂直翻转。
ROTATION_FLAGS: dict[int, int] = {
    0: 0,
    90: FLIP_D | FLIP_H,
    180: FLIP_H | FLIP_V,
    270: FLIP_D | FLIP_V,
}


class TmxError(ValueError):
    """地图格式不受支持或数据损坏。"""


def split_gid(gid: int) -> tuple[int, int]:
    """把一个 GID 拆成 ``(真实图块 ID, 翻转标志)``。"""
    return gid & GID_MASK, gid & FLAG_MASK


def join_gid(base: int, flags: int = 0) -> int:
    """把真实图块 ID 与翻转标志合成一个 GID。"""
    return (base & GID_MASK) | (flags & FLAG_MASK)


# --- 图层数据编解码 -------------------------------------------------------


def decode_gids(data: ET.Element) -> list[int]:
    """解出 ``<data>`` 里的完整 GID 列表（保留翻转标志）。"""
    encoding = data.get("encoding")
    compression = data.get("compression")

    if encoding == "csv":
        # 必须按行拆：直接去掉所有空白会让上一行末尾与下一行开头的
        # 数字粘连成一个数（例如 "1,2,3\n4,5,6" -> "1,2,34,5,6"）。
        gids: list[int] = []
        for line in (data.text or "").splitlines():
            gids.extend(int(part) for part in line.split(",") if part.strip())
        return gids

    if encoding == "base64":
        raw = base64.b64decode("".join((data.text or "").split()))
        if compression == "gzip":
            raw = gzip.decompress(raw)
        elif compression == "zlib":
            raw = zlib.decompress(raw)
        elif compression:
            raise TmxError(f"不支持的图层压缩格式：{compression}")
        if len(raw) % 4:
            raise TmxError("图层数据长度不是 4 字节的整数倍")
        return list(struct.unpack(f"<{len(raw) // 4}I", raw))

    if encoding is None:
        return [int(tile.get("gid", 0)) for tile in data.findall("tile")]

    raise TmxError(f"不支持的图层编码格式：{encoding}")


def encode_gids(data: ET.Element, gids: list[int], width: int) -> None:
    """按 ``<data>`` 原有的编码 / 压缩方式写回 GID 列表。"""
    encoding = data.get("encoding")
    compression = data.get("compression")

    for child in list(data):
        data.remove(child)
    data.text = None

    if encoding == "csv":
        # 行尾逗号是 Tiled 的写法，也保证相邻行拼接时不会把数字粘连。
        rows = [",".join(str(g) for g in gids[i:i + width]) + ","
                for i in range(0, len(gids), width)]
        data.text = "\n" + "\n".join(rows) + "\n"
        return

    if encoding == "base64":
        raw = struct.pack(f"<{len(gids)}I", *gids)
        if compression == "gzip":
            raw = gzip.compress(raw, mtime=0)  # 固定 mtime，保证输出可复现
        elif compression == "zlib":
            raw = zlib.compress(raw, 9)
        elif compression:
            raise TmxError(f"不支持的图层压缩格式：{compression}")
        data.text = base64.b64encode(raw).decode("ascii")
        return

    if encoding is None:
        for gid in gids:
            ET.SubElement(data, "tile", {"gid": str(gid)})
        return

    raise TmxError(f"不支持的图层编码格式：{encoding}")


# --- 模型 -----------------------------------------------------------------


@dataclass
class Layer:
    """一个瓦片图层。``gids`` 始终保留完整的 32 位值（含翻转标志）。"""

    element: ET.Element
    data: ET.Element
    name: str
    width: int
    height: int
    gids: list[int]

    @classmethod
    def parse(cls, element: ET.Element, map_width: int, map_height: int) -> Layer:
        data = element.find("data")
        if data is None:
            raise TmxError(f"图层 {element.get('name')!r} 缺少 <data>")
        width = int(element.get("width") or map_width)
        height = int(element.get("height") or map_height)
        gids = decode_gids(data)
        if len(gids) != width * height:
            raise TmxError(
                f"图层 {element.get('name')!r} 的格子数是 {len(gids)}，"
                f"与尺寸 {width}x{height} 不符"
            )
        return cls(element, data, element.get("name") or "", width, height, gids)

    @property
    def used_gids(self) -> set[int]:
        """本层实际用到的真实图块 ID（已剥离翻转标志）。"""
        return {gid & GID_MASK for gid in self.gids if gid}

    def remap(self, mapping: dict[int, int]) -> None:
        """按 ``旧 gid -> 新 gid`` 重写本层，翻转标志原样保留。"""
        result: list[int] = []
        for raw in self.gids:
            if not raw:
                result.append(0)
                continue
            base, flags = split_gid(raw)
            result.append(join_gid(mapping.get(base, base), flags))
        self.gids = result
        encode_gids(self.data, self.gids, self.width)

    def apply_flags(self, chooser: Callable[[int], int | None]) -> int:
        """逐格设置翻转标志。

        ``chooser(真实图块 ID)`` 返回新的标志值，返回 ``None`` 表示保持原样。
        已有标志会被覆盖，真实图块 ID 不变。返回改动的格子数。
        """
        result: list[int] = []
        changed = 0
        for raw in self.gids:
            base, _old = split_gid(raw)
            flags = chooser(base) if base else None
            if flags is None:
                result.append(raw)
            else:
                result.append(join_gid(base, flags))
                changed += 1
        if changed:
            self.gids = result
            encode_gids(self.data, self.gids, self.width)
        return changed


@dataclass
class Tileset:
    """一个图块集。内嵌 PNG 存放在 ``embedded_png`` 属性里。"""

    element: ET.Element
    first_gid: int
    tile_width: int
    tile_height: int
    columns: int | None
    tile_count: int | None
    name: str = ""
    end_gid: int | None = None  # GID 上界（不含），由 TmxMap 依 firstgid 推算

    @classmethod
    def parse(cls, element: ET.Element) -> Tileset:
        def number(key: str) -> int | None:
            value = element.get(key)
            return int(value) if value is not None else None

        return cls(
            element=element,
            first_gid=number("firstgid") or 1,
            tile_width=number("tilewidth") or 0,
            tile_height=number("tileheight") or 0,
            columns=number("columns"),
            tile_count=number("tilecount"),
            name=element.get("name") or "",
        )

    @property
    def tile_nodes(self) -> dict[int, ET.Element]:
        return {
            int(node.get("id")): node
            for node in self.element.findall("tile")
            if node.get("id") is not None
        }

    @property
    def embedded_png(self) -> ET.Element | None:
        for prop in self.element.findall("properties/property"):
            if prop.get("name") == "embedded_png":
                return prop
        return None

    @property
    def image_source(self) -> str | None:
        image = self.element.find("image")
        return image.get("source") if image is not None else None

    def contains(self, base_gid: int) -> bool:
        if base_gid < self.first_gid:
            return False
        if self.tile_count is not None and base_gid >= self.first_gid + self.tile_count:
            return False
        return self.end_gid is None or base_gid < self.end_gid


class TmxMap:
    """一张 TMX 地图。解析后可原地修改图层与图块集，再序列化回 XML。"""

    def __init__(self, root: ET.Element, layers: list[Layer], tilesets: list[Tileset]):
        self.root = root
        self.layers = layers
        self.tilesets = sorted(tilesets, key=lambda ts: ts.first_gid)
        # Tiled 规范：一个 GID 属于 firstgid 最大且不超过它的图块集。
        # 用下一个图块集的 firstgid 作为上界，比只信 tilecount 更可靠。
        for index, tileset in enumerate(self.tilesets):
            following = (self.tilesets[index + 1].first_gid
                         if index + 1 < len(self.tilesets) else None)
            own_end = (tileset.first_gid + tileset.tile_count
                       if tileset.tile_count is not None else None)
            bounds = [bound for bound in (following, own_end) if bound is not None]
            tileset.end_gid = min(bounds) if bounds else None

    @classmethod
    def from_bytes(cls, data: bytes) -> TmxMap:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(data, parser=parser)
        if root.tag != "map":
            raise TmxError(f"根元素应为 <map>，实际是 <{root.tag}>")
        try:
            width, height = int(root.get("width")), int(root.get("height"))
        except (TypeError, ValueError) as exc:
            raise TmxError("地图缺少合法的 width / height") from exc

        layers = [Layer.parse(el, width, height) for el in root.findall("layer")]
        tilesets = [Tileset.parse(el) for el in root.findall("tileset")]
        return cls(root, layers, tilesets)

    @classmethod
    def from_file(cls, path: str | Path) -> TmxMap:
        return cls.from_bytes(Path(path).read_bytes())

    @property
    def width(self) -> int:
        return int(self.root.get("width"))

    @property
    def height(self) -> int:
        return int(self.root.get("height"))

    @property
    def used_gids(self) -> set[int]:
        used: set[int] = set()
        for layer in self.layers:
            used |= layer.used_gids
        return used

    def unit_layers(self) -> list[Layer]:
        """Rusted Warfare 的 ``Units`` 层（大小写不敏感）。"""
        return [layer for layer in self.layers if layer.name.strip().lower() == "units"]

    def terrain_layers(self) -> list[Layer]:
        return [layer for layer in self.layers if layer not in self.unit_layers()]

    def tileset_for(self, base_gid: int) -> Tileset | None:
        """找出 GID 所属的图块集（firstgid 最大且不超过该 GID）。"""
        for tileset in reversed(self.tilesets):
            if tileset.contains(base_gid):
                return tileset
        return None

    def remap(self, mapping: dict[int, int]) -> None:
        for layer in self.layers:
            layer.remap(mapping)

    def to_bytes(self) -> bytes:
        return ET.tostring(self.root, encoding="utf-8", xml_declaration=True)

    def write(self, path: str | Path) -> None:
        Path(path).write_bytes(self.to_bytes())
