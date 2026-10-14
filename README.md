# zpds-depth-cp

米制 float32 深度文件的有界有损压缩与解压工具。默认采用 **S1：近段线性、远段对数变换 + SZ3，逐帧 T1**。

仅包含文件编解码、Python API、命令行和单元测试；不包含深度估计、光流、模型权重、数据集或实验代码。运行不需要 GPU、CUDA 或 PyTorch。

## 安装

Python 3.11+（Zarr 2.18.7 和 Numcodecs 0.15.1 的最低要求），建议使用独立环境：

```bash
python -m pip install "git+https://github.com/happy-coder-yhy/zpds-depth-cp.git@v0.1.1"
```

本地开发：

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

`tests/` 随源码发布，仅使用程序生成的小数组，不需要数据集或权重；远程 CI 执行单元测试及编解码冒烟检查。

使用 Zarr v2（`zarr>=2.18.7,<3`）、`numcodecs>=0.15.1,<0.16` 和 `pysz==1.0.3`。PySZ 含原生代码，平台需有可用 wheel 或按[官方说明](https://github.com/szcompressor/SZ3/tree/master/tools/pysz)构建；本项目不捆绑 SZ3 二进制。Windows 未验证。

## 命令行

```bash
# 输入必须是米制 float32，形状 (H,W) 或 (T,H,W)
zpds-depth-cp compress depth.npy depth.zarr

# 解压得到米制 float32 NPY；不是恢复有损压缩前的逐位原值
zpds-depth-cp decompress depth.zarr decoded.npy

# 查看元数据、分辨率、块大小、codec 和文件字节数
zpds-depth-cp inspect depth.zarr

# 对照原始数组检查误差预算和例外值位模式
zpds-depth-cp verify depth.npy depth.zarr
```

也可使用 `python -m zpds_depth_cp`。退出码：0 成功，1 文件/参数错误，2 校验发现误差违例。所有命令结果以 JSON 输出。

压缩输入支持 NPY、Zarr v2 根数组或包含 `depth` 数组的 Zarr 目录。拒绝隐式转换 uint16、float64 或已声明为毫米的 Zarr；NPY 和没有单位元数据的 Zarr 由调用方保证单位为米。工具仅保存 `depth` 数组及根属性，不复制同组的其他数组。压缩输出为 `depth[T,H,W]`，原始二维输入经本工具解压仍为二维。

文件转换逐帧读取，不一次加载完整序列；输出先写临时路径，成功后重命名。不覆盖已有输出、不原地修改输入。不要并发写入同一个目标路径。再次压缩已有有损数据会累积误差，预算仅相对于此次输入。

## 误差与格式

z 是压缩前的 float32 深度，单位米。S1 保证的存储误差预算为：

| 输入范围 | 处理方式 | 解压后允许误差 |
|---|---|---|
| 0 < z <= 1m | t = z | <= 1mm |
| 1 < z <= 10m | t = 1 + ln(z) | <= 0.1% × z |
| z > 10m、非正值、NaN、Inf | 无损例外值流 | float32 位模式完全保留 |

这是相对于输入的存储误差，不是传感器或模型相对于真值的准确度。输出 dtype=float32 不代表无损。NaN payload、正负零及异常值均按原始位模式保留。

存储为 Zarr v2，默认块形状 `(1,H,W)`。SZ3 对变换域使用预留 float32 舍入余量的绝对容限；解码器自动反变换为米制深度，调用方不要再取指数。块中包含 CRC32、无损例外掩码和例外值。小块触发 PySZ 已知缓冲区限制时使用原始变换值回退。

保留 `centerdepth.log_sz3.v1` 和旧 `centerdepth.sz3.v1` codec ID，兼容历史文件；导入本包即注册。旧 S 文件按自身元数据中的 alpha 解码，不会自动变成 S1。低层 codec/writer API 保留可配置 alpha 和 chunk_frames 以兼容旧接口，命令行新写入固定 S1/T1。

CRC32 用于检测意外损坏，不提供认证。仅处理可信来源的本地文件；原生 SZ3 解码及解压资源消耗不构成针对恶意输入的安全边界。

## Python API

```python
from zpds_depth_cp import compress, decompress, open_depth, verify

compress("depth.npy", "depth.zarr")
depth = open_depth("depth.zarr")
frame_m = depth[0]               # 按需解码一帧
region_m = depth[0, 100:200, 200:300]
result = verify("depth.npy", "depth.zarr")
assert result["passed"]
decompress("depth.zarr", "decoded.npy")
```

流式写入：

```python
import numpy as np
from zpds_depth_cp import DepthZarrWriter

with DepthZarrWriter("sequence.zarr", height=650, width=800,
                     metadata={"fps": 30.0}) as writer:
    frame_m = np.ones((650, 800), dtype=np.float32)
    writer.append(frame_m)
```

Writer 默认 S1/T1，复制输入帧、不修改原数组；目标必须不存在。使用上下文管理器或调用 `close()` 以写完尾块。直接 Writer 是增量接口，中断后应视为未完成输出；文件转换 API 才提供临时路径提交。

## 许可

本项目代码采用 [MIT](LICENSE)。NumPy、Zarr、Numcodecs、[PySZ/SZ3](https://github.com/szcompressor/SZ3/blob/master/copyright-and-BSD-license.txt) 为独立依赖，分别遵循其原始许可证；不包含模型或训练数据许可。
