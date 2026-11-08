"""测试用的合成 .tmx 地图构造器（无需外部文件）。

结构仿照真实 Rusted Warfare 地图：Ground / Items / Units 三层，
三个带 embedded_png 内嵌图集的 tileset，<tile> 节点带游戏属性。
"""

from __future__ import annotations

import base64
import gzip
import io
import struct
import zlib

from PIL import Image, ImageDraw

TILE = 8
COLS = 4
COUNT = 16

GROUND_FIRST = 1
ITEMS_FIRST = 17
UNITS_FIRST = 33


def atlas_png(offset: int = 0) -> str:
    """4x4 个 8x8 纯色图块，返回 base64 PNG。"""
    image = Image.new("RGBA", (COLS * TILE, COLS * TILE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index in range(COUNT):
        x, y = (index % COLS) * TILE, (index // COLS) * TILE
        colour = ((index * 13 + offset) % 256,
                  (index * 29 + 40) % 256,
                  (index * 7 + 90) % 256, 255)
        draw.rectangle((x, y, x + TILE - 1, y + TILE - 1), fill=colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def encode_layer(gids: list[int], encoding: str, compression: str | None,
                 width: int = 8) -> str:
    if encoding == "csv":
        rows = [",".join(str(g) for g in gids[i:i + width]) + ","
                for i in range(0, len(gids), width)]
        return "\n" + "\n".join(rows) + "\n"
    if encoding == "base64":
        raw = struct.pack(f"<{len(gids)}I", *gids)
        if compression == "gzip":
            raw = gzip.compress(raw, mtime=0)
        elif compression == "zlib":
            raw = zlib.compress(raw)
        return base64.b64encode(raw).decode("ascii")
    if encoding == "xml":
        return "".join(f'<tile gid="{g}"/>' for g in gids)
    raise ValueError(encoding)


def _tileset(first_gid: int, name: str, tile_props: dict[int, str]) -> str:
    tiles = "".join(
        f'<tile id="{i}"><properties>{props}</properties></tile>'
        for i, props in tile_props.items()
    )
    return f'''<tileset firstgid="{first_gid}" name="{name}" tilewidth="{TILE}"
   tileheight="{TILE}" tilecount="{COUNT}" columns="{COLS}">
 <image source="{name}.png" width="32" height="32"/>
 <properties><property name="embedded_png">{atlas_png(first_gid)}</property></properties>
 {tiles}
</tileset>'''


def build_tmx(*, ground: str = "base64", ground_comp: str | None = "gzip",
              units: str = "csv", flipped: bool = True) -> bytes:
    """构造一张 8x8 地图。

    Ground 用到 gid 1~4（其中部分带 Tiled 翻转标志），Items 用到 17/18，
    Units 用到 33/34。其余图块均未被引用，应被压缩掉。
    """
    flag = 0x80000000 if flipped else 0
    ground_gids = [
        (1 | flag), 2, 0, 3, 4, 0, 0, 0,
        2, 0, 0, 0, (3 | flag), 0, 0, 0,
        1, 0, 0, 0, 0, 4, 0, 0,
        0, 0, 3, 0, 0, 0, 2, 0,
        4, 0, 0, 0, 1, 0, 0, 0,
        0, 2, 0, 0, 0, 0, (4 | flag), 0,
        0, 0, 0, 1, 0, 0, 0, 3,
        0, 0, 0, 0, 0, 2, 0, 0,
    ]
    items_gids = [17 if i % 7 == 0 else 0 for i in range(64)]
    items_gids[5] = 18
    units_gids = [33 if i == 0 else (34 if i == 9 else 0) for i in range(64)]

    def layer(name: str, gids: list[int], encoding: str,
              compression: str | None) -> str:
        attrs = f' encoding="{encoding}"' if encoding != "xml" else ""
        attrs += f' compression="{compression}"' if compression else ""
        return (f'<layer name="{name}" width="8" height="8">'
                f'<data{attrs}>{encode_layer(gids, encoding, compression)}</data>'
                f'</layer>')

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<map version="1.9" tiledversion="1.9.1" orientation="orthogonal"
     renderorder="right-down" width="8" height="8" tilewidth="{TILE}"
     tileheight="{TILE}" infinite="0" nextlayerid="4" nextobjectid="1">
 {_tileset(GROUND_FIRST, "ground", {0: '<property name="water"/>',
                                    1: '<property name="cliff"/>',
                                    10: '<property name="unused"/>'})}
 {_tileset(ITEMS_FIRST, "items", {0: '<property name="res_pool"/>'})}
 {_tileset(UNITS_FIRST, "units", {0: '<property name="team" value="0"/><property name="unit" value="commandCenter"/>',
                                   1: '<property name="team" value="1"/><property name="unit" value="builder"/>'})}
 {layer("Ground", ground_gids, ground, ground_comp)}
 {layer("Items", items_gids, "base64", "zlib")}
 {layer("Units", units_gids, units, None)}
</map>'''
    return xml.encode("utf-8")
