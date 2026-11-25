# B2：真实冻结程序的外置模块加载实验

由 ChatGPT 按既有 `unify-python-runtime-and-modular-distribution` 计划推进。
当前为诊断 Core 与验证脚本；Windows 结果以对应运行 artifact 为准，不代表完整产品 Core、
模块安装器或正式发布已经完成。

## 实验边界

- 构建唯一 CPython 3.12.10 的最小 PyInstaller 6.18.0 onedir EXE。
- Core 不冻结 Torch、TorchVision、NumPy、ORT、Qt 或模型权重；外置目录提供这些包。
- 编译器准备环境与依赖准备环境是 CI 临时环境，交付目录只有 Core 中的一份 Python。
  外部运行库拒绝包含另一个 Python EXE/DLL。
- 固定应用源码 `bb3772003f0b8cbd872d9342a48aa4a82d5bb861`，只消费其 DINO 环境检查，
  不修改应用、业务模型、更新协议 3 或完整包构建路径。
- 无正式发布、不上传私有应用源码、不修改现有用户安装。

## 依赖与 DLL 归属

`ci/vision-train-modular-probe-constraints.txt` 来自完整构建 45544329988 的实际依赖快照。
此次仅安装外置加载实验所需的依赖子集；它不是最终模块产品的完整 wheel 锁文件。
pip 安装报告保留来源、版本和下载摘要，运行报告绑定约束文件 SHA。

ORT 只安装 `onnxruntime-gpu==1.23.2`，OpenCV 只安装 Contrib headless 发行包。
Torch、TorchVision 与 CUDA 版本保持已测试的 2.10.0 / 0.25.0 / cu128。

为复现先于 Qt 加载正确 MSVCP 的修复，实验从固定 pandas wheel 提取已经验证过的
单个运行库文件，而不安装或复制整份 pandas：

| 文件 | SHA256 |
| --- | --- |
| `pandas-2.3.3-cp312-cp312-win_amd64.whl` | `a16dcec078a01eeef8ee61bf64074b4e524a2a3f4b3be9326420cabe59c4778b` |
| MSVCP，575,056 字节 | `a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde` |

MSVCP 与原完整包的根运行库完全相同。Core 的 Python ABI forwarder 和 VC 运行库由
同一精确 CPython 安装提供并记录来源。没有改用系统目录搜索来掩盖缺失依赖。

## 实际进程矩阵

| 场景 | 检查内容 |
| --- | --- |
| 不安装外部运行库 | Core 自身启动成功，未导入可选计算模块 |
| 外部纯 Python 包 | 实际导入路径与 distribution metadata 都来自外部目录 |
| 原生扩展 | NumPy 矩阵运算、psutil 扩展、QtCore 调用 |
| Torch/TorchVision | CPU 矩阵运算与原生 NMS；实际 CUDA 运算单独记录 |
| ORT | 冻结进程创建 session 并计算固定 MatMul/Add 图，校验精确输出 |
| DINO 环境 | 原应用环境检查与 ORT CPU 计算；不导入 Torch/训练框架 |
| Windows 文件锁 | 加载 .pyd 后写权限被拒；进程正常退出后恢复，未改写文件内容 |
| 新进程重载 | 更新外部测试包和元数据后，新进程读取新版本；重新创建 ORT session |
| 移除外部目录 | 同一 Core 仍能启动 |

全部场景位于带空格与中文的目录，使用隔离工作目录与子进程环境。记录 PID、退出码、
run_id、Python 版本、实际模块来源、已加载原生库路径和文件摘要；Core 与公共运行库
在测试前后必须保持字节一致，只有明确的外部测试包版本变化。

Python socket/DNS 调用被拒绝并记录；这不等同于 Windows 系统网络已物理断开。
DINO 使用的是原应用 `environment()` 加载路径加独立 ORT 小图，不是完整 DINO worker
协议、实际 DINO 模型或 GPU 业务验收。`sys._MEIPASS` 不被伪造为外部目录。

## 结果如何判定

外部导入、原生计算、文件锁或重载失败都会令运行失败。CPU 加载矩阵通过但 runner 没有
可用 GPU 时，摘要为 `LIMITED`、`cpu_external_loader: PASS`、`gpu_hardware: NOT_RUN`。
只有实际执行 Torch CUDA 运算和 ORT CUDA kernel 才记录 GPU PASS；Provider 名称本身
不能充当 GPU 运算证据。

证据位于 `reports/modular-loader-summary.json` 及各进程报告。小型
`VisionWorkshopProbeCore.zip` 仅用于本实验，不包含产品 GUI 和外部运行库，不能当成
已经缩减完成的 VisionWorkshop 安装包。

## 后续依赖

实验结果用于确定 A4/B3 的模块布局与公共依赖归属，再实现 A5/B4 的离线安装、更新、
卸载与恢复。完整产品仍需接入模块缺失能力判定、外置 DINO DLL/身份清单、新模块协议
与资源定位；保留旧协议 3 的完整包通道。未执行项不能因实验通过而自动勾选。
