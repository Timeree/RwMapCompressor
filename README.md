# RwMapCompressor

Rusted Warfare（铁锈战争）`.tmx` 地图压缩器。扫描所有图层引用的图块，把 tileset 内嵌图集里**没有被用到的图块**涂成透明并删掉多余的 `<tile>` 定义 —— PNG 对大块透明区域的压缩率极高，地图体积因此显著下降。地形、单位、资源池与触发信息全部保留。

原 Java 版的 Python 重写版：修复了旧版缺陷，另加三个可选功能开关。

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

### 默认就修好的问题：旋转图块会被保留

旧版把带旋转 / 翻转标志的 GID 当成负数忽略，导致这些图块对应的贴图被误判为「未使用」而抹成透明。本工具按无符号 32 位解析，剥离高 4 位标志后再匹配图集，并原样保留标志 —— **地图里本来就有旋转图块的，压缩后依然是旋转图块，贴图不会丢**。

这是默认行为，不是开关；工具只保留原有的旋转图块，不会主动给图块加旋转。

### 三个功能开关

| 开关 | 作用 |
| --- | --- |
| `--ignore-units` | 忽略 `Units` 层：清空单位图集的贴图以进一步压缩，但**保留** `<tile>` 上的 `team` / `unit` 定义，游戏里的单位不会消失。Units 图层数据本身不变。 |
| `--obfuscate` | 混淆原始图块：打乱图块在内嵌图集中的位置、紧凑重排并同步改写所有图层的 GID，另对保留图块做确定性像素扰乱。地图逻辑与地形轮廓不变，但内嵌贴图不再能还原为原版素材。 |
| `--minify-xml` | 压缩 XML：去掉标签之间的缩进、换行和注释，无损减小文件体积。`<data>` 的图层数据、`<property>` 里的内嵌 PNG 和所有属性值都原样保留。 |

开关可任意组合，例如：

```bash
# 只压缩 + 忽略单位贴图
rwmapcompressor map.tmx --ignore-units

# 压缩 + 混淆（同一个 seed 输出可复现）
rwmapcompressor map.tmx --obfuscate --seed 42

# 全部功能
rwmapcompressor map.tmx --ignore-units --obfuscate --minify-xml --seed 42
```

### 全部参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `input` | 必填 | 输入 `.tmx` 路径 |
| `-o, --output` | `<文件名>.min.tmx` | 输出路径，不能与输入相同 |
| `--ignore-units` | 关 | 忽略 Units 层贴图 |
| `--obfuscate` | 关 | 混淆原始图块 |
| `--minify-xml` | 关 | 压缩 XML 空白与注释 |
| `--seed` | `0` | 混淆的种子，相同种子输出一致 |

### 作为库使用

```python
from rwmapcompressor import Options, compress

stats = compress("map.tmx", "small.tmx",
                 Options(ignore_units=True, obfuscate=True, minify_xml=True, seed=42))
print(stats.saved_percent)
```

## 格式支持与限制

- 图层数据支持 `base64` + `gzip` / `zlib` / 无压缩、`csv`、以及裸 `<tile gid>` 三种写法；输出保持原编码方式。
- GID 的高 4 位按 [Tiled 规范](https://doc.mapeditor.org/en/stable/reference/global-tile-ids/) 剥离（水平/垂直/对角翻转、六边形 120°），因此旋转过的地块不会被漏算。
- 只有带 `embedded_png` 属性的图集才能压缩贴图；引用外部 `.png` 的图集（如 V4 模板）只能精简 `<tile>` 定义。
- `--obfuscate` 会增加数据熵，输出可能比输入更大，`csv` 图层尤其明显；追求压缩率时请关闭它，或把地图另存为 `Base64 (gzip compressed)`。
- `<image>` 节点与 `<tile>` 上的游戏属性（`water` / `cliff` / `res_pool` / `team` / `unit` 等）均会保留。

## 开发

```bash
python -m unittest discover -s tests -v
```

测试覆盖多种图层编码、GID 标志、csv 多行粘连回归、旋转地块不被误删、三个开关及组合、XML 压缩无损、输出可复现性。
