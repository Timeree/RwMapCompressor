"""压缩流水线：解析 -> 统计使用中的图块 -> 重建图集 -> 写回。

三个可选能力互不依赖，可任意组合：

``ignore_units``  忽略 Units 层引用的图块（清空其贴图，但保留单位定义）
``rotate``        主动给地形图块加上 Tiled 的旋转 / 翻转标志
``obfuscate``     打乱图块在图集中的位置并同步改写图层 GID，另做像素扰乱

无论开关如何，GID 的翻转 / 旋转标志始终会被正确剥离后再匹配图集，
并在输出中原样保留 —— 这修掉了旧版把旋转地块当成负整数忽略的问题。
"""

from __future__ import annotations

import random
import zlib
from dataclasses import dataclass
from pathlib import Path

from .atlas import Atlas, Grid
from .tmx import FLAG_MASK, ROTATION_FLAGS, TmxMap

__all__ = ["Options", "Stats", "compress"]

_ROTATABLE_ANGLES = (90, 180, 270)


@dataclass(frozen=True)
class Options:
    """所有开关集中在一处，方便测试与复用。"""

    ignore_units: bool = False
    rotate: bool = False
    rotate_angle: int = 0            # 0 表示逐格随机选 90/180/270
    rotate_ratio: float = 1.0        # 参与旋转的格子比例
    obfuscate: bool = False
    seed: int = 0                    # 混淆与旋转的随机种子，保证输出可复现

    def __post_init__(self) -> None:
        if self.rotate_angle not in (0, *_ROTATABLE_ANGLES):
            raise ValueError("--rotate-angle 只能是 0 / 90 / 180 / 270")
        if not 0.0 <= self.rotate_ratio <= 1.0:
            raise ValueError("--rotate-ratio 必须在 0 到 1 之间")


@dataclass
class Stats:
    input_size: int = 0
    output_size: int = 0
    width: int = 0
    height: int = 0
    layer_count: int = 0
    used_gids: int = 0
    flipped_cells: int = 0
    kept_tiles: int = 0
    removed_tile_nodes: int = 0
    rotated_cells: int = 0
    remapped_gids: int = 0
    atlas_count: int = 0

    @property
    def saved_bytes(self) -> int:
        return self.input_size - self.output_size

    @property
    def saved_percent(self) -> float:
        if not self.input_size:
            return 0.0
        return self.saved_bytes / self.input_size * 100


def _layer_seed(seed: int, name: str) -> int:
    return seed ^ zlib.crc32(name.encode("utf-8"))


def _apply_rotation(tmx: TmxMap, options: Options) -> int:
    """给地形层逐格设置旋转标志；Units 层不参与（单位不该被旋转）。"""
    changed = 0
    for layer in tmx.terrain_layers():
        rng = random.Random(_layer_seed(options.seed, layer.name))

        def chooser(_base: int, *, _rng: random.Random = rng) -> int | None:
            if _rng.random() > options.rotate_ratio:
                return None
            angle = options.rotate_angle or _rng.choice(_ROTATABLE_ANGLES)
            return ROTATION_FLAGS[angle]

        changed += layer.apply_flags(chooser)
    return changed


def compress(source: str | Path, target: str | Path,
             options: Options | None = None) -> Stats:
    """压缩一张 ``.tmx`` 地图并写到 ``target``，返回统计信息。"""
    options = options or Options()
    raw = Path(source).read_bytes()
    tmx = TmxMap.from_bytes(raw)

    stats = Stats(
        input_size=len(raw),
        width=tmx.width,
        height=tmx.height,
        layer_count=len(tmx.layers),
    )
    stats.flipped_cells = sum(
        1 for layer in tmx.layers for gid in layer.gids if gid & FLAG_MASK
    )

    # 1. 统计真实使用中的 GID。used_gids 已剥离 4 个标志位 —— 旋转修复在此。
    used = tmx.used_gids
    unit_gids: set[int] = set()
    for layer in tmx.unit_layers():
        unit_gids |= layer.used_gids
    if options.ignore_units:
        used -= unit_gids
    stats.used_gids = len(used)

    # 2. 可选的主动旋转（只改标志位，不影响图块归属）。
    if options.rotate:
        stats.rotated_cells = _apply_rotation(tmx, options)

    # 3. 把使用中的 GID 归到各自的图块集。
    keep_by_ts: dict[int, set[int]] = {id(ts): set() for ts in tmx.tilesets}
    unit_local_by_ts: dict[int, set[int]] = {id(ts): set() for ts in tmx.tilesets}
    for gid in used:
        tileset = tmx.tileset_for(gid)
        if tileset is not None:
            keep_by_ts[id(tileset)].add(gid - tileset.first_gid)
    for gid in unit_gids:
        tileset = tmx.tileset_for(gid)
        if tileset is not None:
            unit_local_by_ts[id(tileset)].add(gid - tileset.first_gid)

    # 4. 逐图块集重建内嵌图集、精简 <tile> 节点，并收集全局 GID 映射。
    gid_map: dict[int, int] = {}
    for tileset in tmx.tilesets:
        keep = keep_by_ts[id(tileset)]
        unit_local = (unit_local_by_ts[id(tileset)]
                      if options.ignore_units else set())
        prop = tileset.embedded_png

        if prop is not None:
            atlas = Atlas.load(prop)
            grid = Grid.for_tileset(tileset, atlas.image.size)
            keep = {local for local in keep if 0 <= local < grid.capacity}
            local_map = atlas.rebuild(
                grid, keep,
                shuffle=options.obfuscate,
                seed=options.seed ^ tileset.first_gid,
                scramble=options.obfuscate,
            )
            atlas.save()
            stats.atlas_count += 1
        else:
            # 外部图集（V4 模板）没有内嵌 PNG，只能精简 <tile> 定义。
            local_map = {local: local for local in keep}
        stats.kept_tiles += len(keep)

        for old, new in local_map.items():
            if old != new:
                gid_map[tileset.first_gid + old] = tileset.first_gid + new

        # 单位定义靠 <tile> 的 properties（team / unit）保存，即使忽略
        # Units 层贴图也必须留着这些节点，否则游戏里的单位会消失。
        preserved = set(local_map) | (unit_local & set(tileset.tile_nodes))
        for node in list(tileset.element.findall("tile")):
            raw_id = node.get("id")
            if raw_id is None:
                continue
            old = int(raw_id)
            if old not in preserved:
                tileset.element.remove(node)
                stats.removed_tile_nodes += 1
            elif old != local_map.get(old, old):
                node.set("id", str(local_map[old]))

    if gid_map:
        tmx.remap(gid_map)
        stats.remapped_gids = len(gid_map)

    output = tmx.to_bytes()
    Path(target).write_bytes(output)
    stats.output_size = len(output)
    return stats
