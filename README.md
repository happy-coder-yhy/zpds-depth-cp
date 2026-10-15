# zpds-depth-cp

本项目仓库为一套面向米制 float32 深度文件的解压缩工具，支持NPY和Zarr，提供S1、S2、S3三档精度，默认配置使用S2，使用CPU运行，不依赖GPU或CUDA。

## 安装

需要 Python 3.11+。

```bash
python -m pip install "git+https://github.com/happy-coder-yhy/zpds-depth-cp.git@main"
```

依赖 Zarr v2、Numcodecs 和 PySZ 1.0.3。PySZ 如无当前平台的 wheel，可按[官方说明](https://github.com/szcompressor/SZ3/tree/master/tools/pysz)编译安装。

## 压缩与解压

输入为米制 float32 数组，形状是单帧 `(H,W)` 或序列 `(T,H,W)`。具体命令行使用方法如下：

```bash
# 使用默认S2精度压缩，保存为depth_s2.zarr
zpds-depth-cp compress depth.npy depth_s2.zarr
```

```bash
# 使用S1精度压缩，通过设置--preset参数来选择精度
zpds-depth-cp compress depth.npy depth_s1.zarr --preset S1
```

```bash
# 将压缩文件解压为NumPy数组，保存为decoded.npy
zpds-depth-cp decompress depth_s2.zarr decoded.npy
```

```bash
# 查看压缩文件的形状、精度档位和编码信息
zpds-depth-cp inspect depth_s2.zarr
```

```bash
# 对照原始深度，校验压缩文件的重建误差是否符合精度要求
zpds-depth-cp verify depth.npy depth_s2.zarr
```

`--preset` 接受S1、S2、S3，大小写均可。解压和校验自动从文件读取精度参数。命令结果为JSON；退出码0表示成功，1表示文件或参数错误，2表示校验失败或命令行用法错误。

压缩也接受Zarr v2根数组，或带有 `depth` 数组的Zarr目录。输出内容为深度数组和根属性。程序逐帧处理，新文件写完后再提交到目标路径；目标路径已存在时，命令报错并保留原文件。

## 精度怎么选

三档共用一种编码方式，只改变误差容限。表中误差是解压值与输入值的最大允许偏差。

| 档位 | alpha | 0 < z <= 1m | 1 < z <= 10m | 5m 处 | 10m 处 |
|---|---:|---:|---:|---:|---:|
| S1 | 0.001 | 1mm | 0.1% × z | 5mm | 10mm |
| S2，默认 | 0.002 | 2mm | 0.2% × z | 10mm | 20mm |
| S3 | 0.003 | 3mm | 0.3% × z | 15mm | 30mm |

S1 保留更多细节；S2、S3 放宽容限，通常能得到更小的文件。超过 10m 的值，以及零、负值、NaN、Inf，三档都逐位保留。

例如，S2 对 0.8m 深度允许 2mm 偏差，对 5m 深度允许 10mm 偏差。解压结果仍是 float32；有损压缩丢掉的细节不会恢复。切换档位时应从原始深度重新压缩，避免多次有损编码累积误差。

## 实验数据

为验证压缩性能，在含深度GT的公开数据集上进行实验。包括FAT mixed（30 帧，800×450）、Dynamic Replica valid（40 帧，800×450）和Booster train/balanced（38 帧，800×585）。三档均压缩同一份FFS float32深度，按单帧分块。

| 数据集 | 档位 | 压缩后体积 / MiB | 压缩比 | 压缩 MAE / mm |
|---|---|---:|---:|---:|
| FAT | S1 | 2.029 | 20.3× | 0.6889 |
| FAT | S2 | 1.504 | 27.4× | 1.1334 |
| FAT | S3 | 1.325 | 31.1× | 1.6536 |
| Dynamic Replica | S1 | 2.413 | 22.8× | 0.9790 |
| Dynamic Replica | S2 | 1.553 | 35.4× | 1.6620 |
| Dynamic Replica | S3 | 1.231 | 44.6× | 2.3013 |
| Booster | S1 | 1.594 | 42.6× | 0.4440 |
| Booster | S2 | 0.996 | 68.1× | 0.7644 |
| Booster | S3 | 0.802 | 84.6× | 1.0777 |

压缩比为原始float32数组字节数与Zarr完整体积之比。压缩MAE以原始深度为参照，先逐图计算，再在数据集内等权平均。全部九组测试的误差超限像素数和例外值逐位不一致数均为 **0**。

下表比较原始FFS深度和解压深度对GT的误差。各项按相同有效像素汇总，单位为mm；ΔMAE = 解压后对GT的MAE − 原始FFS对GT的MAE。

| 数据集 | GT距离范围 | 原始FFS MAE | S1 ΔMAE | S2 ΔMAE | S3 ΔMAE |
|---|---|---:|---:|---:|---:|
| FAT | 全距离 | 319.8598 | +0.0207 | +0.0920 | +0.2106 |
| FAT | 0.5–1m | 28.3402 | +0.0275 | +0.0954 | +0.2844 |
| Dynamic Replica | 全距离 | 85.2633 | +0.0183 | +0.0626 | +0.1368 |
| Dynamic Replica | 0.5–1m | 8.4959 | +0.0066 | +0.0239 | +0.0519 |
| Booster | 全距离 | 1781.2114 | +0.0185 | +0.0879 | +0.1608 |
| Booster | 0.5–1m | 24.5213 | +0.0159 | +0.1127 | +0.1994 |

全距离统计保留了FFS的极端深度预测，这些值会抬高MAE；近场误差统计选取真值深度在 `0.5 < z <= 1m` 范围内的像素。采样方式、压缩后MAE及统计数据见 [评测记录](benchmarks/public-datasets.json)。

## Python API

文件转换与按需读取：

```python
from zpds_depth_cp import compress, decompress, open_depth, verify

# 使用 S2 精度压缩深度数组
compress("depth.npy", "depth_s2.zarr", preset="S2")

depth = open_depth("depth_s2.zarr")

frame_m = depth[0]
region_m = depth[0, 100:200, 200:300]

report = verify("depth.npy", "depth_s2.zarr")
assert report["passed"]

# 将完整深度数组解压并保存为 NPY 文件
decompress("depth_s2.zarr", "decoded.npy")
```

流式写入：

```python
import numpy as np
from zpds_depth_cp import DepthZarrWriter

# 创建深度序列文件
with DepthZarrWriter("sequence.zarr", height=650, width=800,
                     preset="S3", metadata={"fps": 30.0}) as writer:
    writer.append(np.ones((650, 800), dtype=np.float32))
```

Writer 默认 S2，每个块存一帧。使用 `with` 或 `close()` 写完尾块。自定义容限仍可通过 `alpha` 设置，例如 `alpha=0.0005`；`alpha` 与 `preset` 二选一。

## 文件格式

输出是 Zarr v2 的 `depth[T,H,W]` 数组，dtype 为 float32，默认块形状为 `(1,H,W)`。单帧 NPY 经本工具压缩后，解压仍恢复为二维数组。

编码分两段：1m 内使用 `t=z`，1–10m 使用 `t=1+ln(z)`，再由 SZ3 压缩。解码器完成反变换，读取到的数值直接以米表示。块内存有 CRC32 校验码、例外值掩码及例外值；小块遇到 PySZ 缓冲区限制时回退为保存原始变换值。

导入 `zpds_depth_cp` 后会注册 `centerdepth.log_sz3.v1` 和 `centerdepth.sz3.v1`，已有文件可以继续读取。`inspect` 和 `verify` 根据 codec 的实际 alpha 显示档位，自定义容限显示为 `custom`。

输入单位须为米，uint16 毫米深度应先换算为 float32 米制数组，CRC32 用于检查数据损坏。

## 开发与测试

```bash
git clone https://github.com/happy-coder-yhy/zpds-depth-cp.git
cd zpds-depth-cp
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用生成的小数组，覆盖三档精度、特殊值、旧文件兼容和命令行转换。

## 许可

项目采用 [MIT](LICENSE)。NumPy、Zarr、Numcodecs 和 [PySZ/SZ3](https://github.com/szcompressor/SZ3/blob/master/copyright-and-BSD-license.txt) 沿用各自许可证。
