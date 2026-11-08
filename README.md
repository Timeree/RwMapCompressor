# RwMapCompressor

Rusted Warfare（铁锈战争）`.tmx` 地图压缩器。扫描所有图层引用的图块，把 tileset 内嵌图集里**没有被用到的图块**涂成透明并删掉多余的 `<tile>` 定义 —— PNG 对大块透明区域的压缩率极高，地图体积因此显著下降。地图的地形、单位、资源池与触发信息全部保留。

原 Java 版的 Python 重写版，另加三个可选功能开关。

## 安装

需要 Python 3.10+。

```bash
pip install -r requirements.txt
# 或安装为命令
pip install .
```

## 用法

```bash
# 输出默认写到同目录的 <文件名>.min.tmx
python -m rwmapcompressor map.tmx
# 安装后也可以直接用命令
rwmapcompressor map.tmx -o small.tmx
```

程序会打印输入/输出体积、图层数、保留图块数、删除的 `<tile>` 定义数及压缩率。

### 三个功能开关

| 开关 | 作用 |
| --- | --- |
| `--ignore-units` | 忽略 `Units` 层：清空单位图集的贴图以进一步压缩，但**保留** `<tile>` 上的 `team` / `unit` 定义，游戏里的单位不会消失。Units 图层数据本身不变。 |
| `--rotate` | 主动给地形图块加 Tiled 的旋转 / 翻转标志（90°/180°/270°）。Units 层不参与。此外，无论此开关是否开启，工具都会正确解析并保留地图中**已有**的旋转标志 —— 旧版会把它们当成负数 gid 而误删对应贴图，这里已修复。 |
| `--obfuscate` | 混淆原始图块：打乱图块在内嵌图集中的位置、紧凑重排并同步改写所有图层的 GID，另对保留图块做确定性像素扰乱。地图逻辑与地形轮廓不变，但内嵌贴图不再能还原为原版素材，也无法按原图集顺序对照。 |

开关可任意组合，例如：

```bash
# 只压缩 + 忽略单位贴图
rwmapcompressor map.tmx --ignore-units

# 压缩 + 混淆（同一个 seed 输出可复现）
rwmapcompressor map.tmx --obfuscate --seed 42

# 全部功能
rwmapcompressor map.tmx --rotate --rotate-angle 90 --obfuscate --ignore-units
```

### 全部参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `input` | 必填 | 输入 `.tmx` 路径 |
| `-o, --output` | `<文件名>.min.tmx` | 输出路径，不能与输入相同 |
| `--ignore-units` | 关 | 忽略 Units 层 |
| `--rotate` | 关 | 主动旋转地形图块 |
| `--rotate-angle` | `0` | `0`/`90`/`180`/`270`；`0` 表示逐格随机 |
| `--rotate-ratio` | `1.0` | 参与旋转的格子比例，0~1 |
| `--obfuscate` | 关 | 混淆原始图块 |
| `--seed` | `0` | 混淆与旋转的种子，相同种子输出一致 |

### 作为库使用

```python
from rwmapcompressor import Options, compress

stats = compress("map.tmx", "small.tmx",
                 Options(ignore_units=True, obfuscate=True, seed=42))
print(stats.saved_percent)
```

## 格式支持与限制

- 图层数据支持 `base64` + `gzip` / `zlib` / 无压缩、`csv`、以及裸 `<tile gid>` 三种写法；输出保持原编码方式。
- GID 的高 4 位按 [Tiled 规范](https://doc.mapeditor.org/en/stable/reference/global-tile-ids/) 剥离（水平/垂直/对角翻转、六边形 120°），因此旋转过的地块不会被漏算。
- 只有带 `embedded_png` 属性的图集才能压缩贴图；引用外部 `.png` 的图集（如 V4 模板）只能精简 `<tile>` 定义。
- `--rotate` 与 `--obfuscate` 会增加数据熵，输出可能比输入更大，`csv` 图层尤其明显；追求压缩率时请关闭它们，或把地图另存为 `Base64 (gzip compressed)`。
- `<image>` 节点与 `<tile>` 上的游戏属性（`water` / `cliff` / `res_pool` / `team` / `unit` 等）均会保留。

## 开发

```bash
python -m unittest discover -s tests -v
```

测试覆盖多种图层编码、GID 标志、csv 多行粘连回归、旋转地块不被误删、三个开关及组合、输出可复现性。
