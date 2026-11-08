"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Options, Stats, compress

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rwmapcompressor",
        description="压缩 Rusted Warfare 的 .tmx 地图：删除未使用的图块贴图。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  rwmapcompressor map.tmx
  rwmapcompressor map.tmx -o small.tmx --ignore-units
  rwmapcompressor map.tmx --obfuscate --seed 42
  rwmapcompressor map.tmx --minify-xml --ignore-units
""",
    )
    parser.add_argument("input", type=Path, help="输入 .tmx 地图路径")
    parser.add_argument("-o", "--output", type=Path,
                        help="输出路径（默认：输入文件同目录下的 <文件名>.min.tmx）")

    parser.add_argument("--ignore-units", action="store_true",
                        help="忽略 Units 层：清空单位图集贴图（保留单位定义）")
    parser.add_argument("--obfuscate", action="store_true",
                        help="混淆原始图块：打乱图集内位置并改写图层 GID，另做像素扰乱")
    parser.add_argument("--minify-xml", action="store_true",
                        help="压缩 XML：去掉缩进 / 换行 / 注释，无损减小文件体积")
    parser.add_argument("--seed", type=int, default=0,
                        help="混淆的随机种子，相同种子输出可复现（默认 0）")
    return parser


def default_output(source: Path) -> Path:
    return source.with_name(source.stem + ".min.tmx")


def _print_report(source: Path, target: Path, stats: Stats,
                  options: Options) -> None:
    print("《压缩结果》")
    print(f"  输入      : {source}  ({stats.input_size / 1024:.1f} KB)")
    print(f"  输出      : {target}  ({stats.output_size / 1024:.1f} KB)")
    print(f"  地图尺寸  : {stats.width}x{stats.height}，{stats.layer_count} 个图层")
    print(f"  使用图块  : {stats.kept_tiles} 个（引用 {stats.used_gids} 个 GID）")
    print(f"  内嵌图集  : {stats.atlas_count} 张，删除 <tile> 定义 {stats.removed_tile_nodes} 个")
    if stats.flipped_cells:
        print(f"  旋转图块  : 检测到 {stats.flipped_cells} 个，已正确保留（不会误删贴图）")
    if options.obfuscate:
        print(f"  混淆图块  : 重映射 {stats.remapped_gids} 个 GID")
    if options.minify_xml:
        print(f"  XML 压缩  : 空白 / 注释省下 {stats.xml_saved_bytes / 1024:.1f} KB")
    print(f"  体积减少  : {stats.saved_bytes / 1024:.1f} KB ({stats.saved_percent:.1f}%)")
    if stats.output_size > stats.input_size:
        print("  提示      : 输出比输入大。混淆会增加数据熵，csv 图层尤为明显；"
              "如需压缩率，请改用 base64 (gzip) 图层或关闭混淆。")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source: Path = args.input
    if not source.is_file():
        parser.error(f"输入文件不存在：{source}")
    target: Path = args.output or default_output(source)
    if target.resolve() == source.resolve():
        parser.error("输出路径不能与输入路径相同")

    try:
        options = Options(
            ignore_units=args.ignore_units,
            obfuscate=args.obfuscate,
            minify_xml=args.minify_xml,
            seed=args.seed,
        )
        stats = compress(source, target, options)
    except (ValueError, OSError) as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 1

    _print_report(source, target, stats, options)
    return 0
