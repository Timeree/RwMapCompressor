# RwMapCompressor

Rusted Warfare（铁锈战争）`.tmx` 地图压缩器。扫描图层引用的图块，将 tileset 内嵌图集中未使用的图块涂透明并删除多余 `<tile>` 定义；地形、单位、资源池与触发信息保留。

Python 3.10+。

## 安装

```bash
pip install .
# 或仅装依赖
pip install -r requirements.txt
```

## 用法

```bash
rwmapcompressor map.tmx                  # 输出 map.min.tmx
rwmapcompressor map.tmx -o small.tmx
python -m rwmapcompressor map.tmx        # 免安装
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `input` | 必填 | 输入 `.tmx` 路径 |
| `-o, --output` | `<name>.min.tmx` | 输出路径，不可与输入相同 |
| `--ignore-units` | 关 | 清空 Units 图集贴图，保留 `team` / `unit` 定义 |
| `--obfuscate` | 关 | 打乱图集图块位置、紧凑重排并同步改写图层 GID |
| `--minify-xml` | 关 | 去除标签间空白与注释 |
| `--seed` | `0` | 混淆种子，同种子输出一致 |

开关可任意组合：

```bash
rwmapcompressor map.tmx --ignore-units --obfuscate --minify-xml --seed 42
```

## 技术说明

- 图层数据支持 `base64` + `gzip` / `zlib` / 无压缩、`csv`、裸 `<tile gid>`；输出保持原编码。
- GID 按 [Tiled 规范](https://doc.mapeditor.org/en/stable/reference/global-tile-ids/) 剥离高 4 位翻转/旋转标志后匹配图集，标志原样保留。旧 Java 版按有符号 int 解析会漏算旋转图块，此为默认修复，无开关，也不主动添加旋转。
- 仅带 `embedded_png` 的图集可压缩贴图；引用外部 `.png` 的图集（如 V4 模板）只精简 `<tile>` 定义。
- `<image>` 节点与 `<tile>` 上的游戏属性（`water` / `cliff` / `res_pool` / `team` / `unit` 等）均保留。
- `--obfuscate` 增加数据熵，输出可能变大，`csv` 图层尤甚；追求压缩率时关闭，或另存为 `Base64 (gzip compressed)`。

## 库调用

```python
from rwmapcompressor import Options, compress

stats = compress("map.tmx", "small.tmx", Options(ignore_units=True, seed=42))
print(stats.saved_percent)
```

## 开发

```bash
python -m unittest discover -s tests -v
```

## 待实测

尚未在 Rusted Warfare 客户端实机加载验证，使用前请自行确认输出地图可正常打开、地形与单位无缺失。
