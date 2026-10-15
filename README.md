# zpds-depth-cp

压缩和解压米制 float32 深度文件，支持 NPY 和 Zarr。提供 S1、S2、S3 三档精度，默认 S1，使用 CPU 运行。

## 安装

需要 Python 3.11+。

```bash
python -m pip install "git+https://github.com/happy-coder-yhy/zpds-depth-cp.git@v0.2.0"
```

依赖 Zarr v2、Numcodecs 和 PySZ 1.0.3。PySZ 如无当前平台的 wheel，可按[官方说明](https://github.com/szcompressor/SZ3/tree/master/tools/pysz)编译安装。Windows 尚未测试。

## 压缩与解压

输入为米制 float32 数组，形状是单帧 `(H,W)` 或序列 `(T,H,W)`。

```bash
zpds-depth-cp compress depth.npy depth_s1.zarr
zpds-depth-cp compress depth.npy depth_s2.zarr --preset S2
zpds-depth-cp compress depth.npy depth_s3.zarr --preset S3

zpds-depth-cp decompress depth_s2.zarr decoded.npy
zpds-depth-cp inspect depth_s2.zarr
zpds-depth-cp verify depth.npy depth_s2.zarr
```

`--preset` 接受 S1、S2、S3，大小写均可。解压和校验从文件读取精度参数，无需再次指定。命令结果为 JSON；退出码 0 表示成功，1 表示文件或参数错误，2 表示校验未通过或命令行用法错误。

压缩也接受 Zarr v2 根数组，或带有 `depth` 数组的 Zarr 目录。输出保存深度和根属性，不复制其他数组。程序逐帧处理，新文件写完后再提交到目标路径；已有输出不会被覆盖。

## 精度怎么选

三档共用一种编码方式，只改变误差容限。表中误差是解压值与输入值的最大允许偏差。

| 档位 | alpha | 0 < z <= 1m | 1 < z <= 10m | 5m 处 | 10m 处 |
|---|---:|---:|---:|---:|---:|
| S1，默认 | 0.001 | 1mm | 0.1% × z | 5mm | 10mm |
| S2 | 0.002 | 2mm | 0.2% × z | 10mm | 20mm |
| S3 | 0.003 | 3mm | 0.3% × z | 15mm | 30mm |

S1 保留更多细节；S2、S3 放宽容限，通常能得到更小的文件。超过 10m 的值，以及零、负值、NaN、Inf，三档都逐位保留。

例如，S2 对 0.8m 深度允许 2mm 偏差，对 5m 深度允许 10mm 偏差。解压结果仍是 float32；有损压缩丢掉的细节不会恢复。切换档位时应从原始深度重新压缩，避免多次有损编码累积误差。

## Python API

文件转换与按需读取：

```python
from zpds_depth_cp import compress, decompress, open_depth, verify

compress("depth.npy", "depth_s2.zarr", preset="S2")
depth = open_depth("depth_s2.zarr")
frame_m = depth[0]
region_m = depth[0, 100:200, 200:300]

report = verify("depth.npy", "depth_s2.zarr")
assert report["passed"]
decompress("depth_s2.zarr", "decoded.npy")
```

流式写入：

```python
import numpy as np
from zpds_depth_cp import DepthZarrWriter

with DepthZarrWriter("sequence.zarr", height=650, width=800,
                     preset="S3", metadata={"fps": 30.0}) as writer:
    writer.append(np.ones((650, 800), dtype=np.float32))
```

Writer 默认 S1，每个块存一帧。使用 `with` 或 `close()` 写完尾块。自定义容限仍可通过 `alpha` 设置，例如 `alpha=0.0005`；`alpha` 与 `preset` 二选一。

## 文件格式

输出是 Zarr v2 的 `depth[T,H,W]` 数组，dtype 为 float32，默认块形状为 `(1,H,W)`。单帧 NPY 经本工具压缩后，解压仍恢复为二维数组。

编码分两段：1m 内使用 `t=z`，1–10m 使用 `t=1+ln(z)`，再由 SZ3 压缩。解码器完成反变换，读取到的数值直接以米表示。块内存有 CRC32 校验码、例外值掩码及例外值；小块遇到 PySZ 缓冲区限制时回退为保存原始变换值。

导入 `zpds_depth_cp` 后会注册 `centerdepth.log_sz3.v1` 和旧版 `centerdepth.sz3.v1`，已有文件可以继续读取。`inspect` 和 `verify` 根据 codec 的实际 alpha 显示档位，自定义容限显示为 `custom`。

输入单位须为米。uint16 毫米深度应先换算为 float32 米制数组。请只解码可信来源的文件；CRC32 仅用于检查数据损坏。

## 开发与测试

```bash
git clone https://github.com/happy-coder-yhy/zpds-depth-cp.git
cd zpds-depth-cp
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用生成的小数组，覆盖三档精度、特殊值、旧文件兼容和命令行转换。GitHub Actions 在 Python 3.11、3.12、3.13 上运行。

## 许可

项目采用 [MIT](LICENSE)。NumPy、Zarr、Numcodecs 和 [PySZ/SZ3](https://github.com/szcompressor/SZ3/blob/master/copyright-and-BSD-license.txt) 沿用各自许可证。
