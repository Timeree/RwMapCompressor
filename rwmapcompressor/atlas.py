"""tileset 内嵌 PNG 图集的瓦片级操作。

Rusted Warfare 把地形贴图以 ``<property name="embedded_png">`` 的形式
base64 内嵌在 ``.tmx`` 里。压缩的核心就是：把没有被任何图层引用的瓦片
区域涂成全透明，PNG 编码器会把这些大块透明区域压得极小。
"""

from __future__ import annotations

import base64
import io
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from PIL import Image

from .tmx import Tileset

__all__ = ["Grid", "Atlas", "AtlasError"]

TRANSPARENT = (0, 0, 0, 0)


class AtlasError(ValueError):
    """内嵌图集无法解析。"""


@dataclass(frozen=True)
class Grid:
    """图集的瓦片网格几何。"""

    tile_width: int
    tile_height: int
    columns: int
    rows: int
    margin: int = 0
    spacing: int = 0

    @classmethod
    def for_tileset(cls, tileset: Tileset, size: tuple[int, int]) -> Grid:
        tw, th = tileset.tile_width, tileset.tile_height
        if tw <= 0 or th <= 0:
            raise AtlasError(f"图集 {tileset.name!r} 缺少合法的 tilewidth / tileheight")
        columns = tileset.columns or (size[0] // tw)
        rows = size[1] // th
        if columns <= 0 or rows <= 0:
            raise AtlasError(f"图集 {tileset.name!r} 的尺寸 {size} 无法切分瓦片")
        return cls(
            tile_width=tw,
            tile_height=th,
            columns=columns,
            rows=rows,
            margin=int(tileset.element.get("margin") or 0),
            spacing=int(tileset.element.get("spacing") or 0),
        )

    @property
    def capacity(self) -> int:
        return self.columns * self.rows

    def rect(self, local_id: int) -> tuple[int, int, int, int]:
        x = self.margin + (local_id % self.columns) * (self.tile_width + self.spacing)
        y = self.margin + (local_id // self.columns) * (self.tile_height + self.spacing)
        return x, y, x + self.tile_width, y + self.tile_height


class Atlas:
    """一张内嵌 PNG 图集，持有其 XML 属性节点。"""

    def __init__(self, prop: ET.Element, image: Image.Image):
        self.prop = prop
        self.image = image.convert("RGBA")

    @classmethod
    def load(cls, prop: ET.Element) -> Atlas:
        try:
            raw = base64.b64decode("".join((prop.text or "").split()))
            image = Image.open(io.BytesIO(raw))
            image.load()
        except (ValueError, OSError) as exc:
            raise AtlasError(f"embedded_png 不是合法的 base64 PNG：{exc}") from exc
        return cls(prop, image)

    def save(self) -> None:
        buffer = io.BytesIO()
        self.image.save(buffer, format="PNG", optimize=True)
        self.prop.text = base64.b64encode(buffer.getvalue()).decode("ascii")

    def rebuild(self, grid: Grid, keep: set[int], *, shuffle: bool, seed: int,
                scramble: bool) -> dict[int, int]:
        """重建图集：只保留 ``keep`` 中的瓦片，返回 ``旧局部 ID -> 新局部 ID``。

        ``shuffle=True`` 时，保留的瓦片会被确定性打乱并紧凑排到网格头部，
        同时打乱图层里的 GID 引用 —— 这就是「混淆原始图块」。
        ``scramble=True`` 时还会对保留瓦片做确定性的像素扰乱。
        """
        ordered = sorted(local_id for local_id in keep if 0 <= local_id < grid.capacity)
        if shuffle:
            # 新槽位 0..N-1 由乱序后的旧 ID 依次填充：位置被打乱且紧凑。
            rng = random.Random(seed)
            shuffled = ordered[:]
            rng.shuffle(shuffled)
            mapping = {old: slot for slot, old in enumerate(shuffled)}
        else:
            mapping = {local_id: local_id for local_id in ordered}

        rebuilt = Image.new("RGBA", self.image.size, TRANSPARENT)
        for old, new in mapping.items():
            rebuilt.paste(self.image.crop(grid.rect(old)), grid.rect(new)[:2])

        if scramble:
            for new in mapping.values():
                self._scramble_tile(rebuilt, grid.rect(new), seed ^ (new * 0x9E3779B1))

        self.image = rebuilt
        return mapping

    @staticmethod
    def _scramble_tile(image: Image.Image, rect: tuple[int, int, int, int],
                       seed: int) -> None:
        """对单个瓦片做确定性像素扰乱：通道轮换 + 每通道亮度偏移。

        Alpha 通道保持不变，因此地形轮廓与透明区域不受影响。
        """
        rng = random.Random(seed)
        tile = image.crop(rect)
        red, green, blue, alpha = tile.split()
        channels = [red, green, blue]
        rng.shuffle(channels)
        offset = rng.randint(-32, 32)
        lut = [max(0, min(255, value + offset)) for value in range(256)]
        shifted = [channel.point(lut) for channel in channels]
        image.paste(Image.merge("RGBA", (*shifted, alpha)), rect[:2])
