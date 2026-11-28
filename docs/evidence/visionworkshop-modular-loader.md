# B2：真实冻结程序的外置模块加载实验

由 ChatGPT 按既有 `unify-python-runtime-and-modular-distribution` 计划推进。
当前为诊断 Core 与验证脚本；Windows 结果以对应运行 artifact 为准，不代表完整产品 Core、
模块安装器或正式发布已经完成。

## 最新实际结果：CPU 外置加载矩阵通过，GPU 未执行

[运行 45585355615](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45585355615)
绑定打包提交 `b8cd91e9c72a682cd5efce91ac713100601da488`，工作流成功；报告为
**`cpu_external_loader: PASS`、`status: LIMITED`、`gpu_hardware: NOT_RUN`**。
已下载 artifact `15009320244` 并核对 ZIP SHA256：
`c6ee177a39f12f1de567fc9c2645647d4aeac6dd8d96e2dac6340f19bda6ec79`。
仓库保留[摘要、逐进程检查与原始报告摘要](visionworkshop-modular-loader-45585355615.json)。

十个真实 EXE 进程场景全部通过：无外部运行库启动、纯 Python 与 metadata、NumPy/psutil/Qt、
Torch CPU 矩阵与 TorchVision NMS/PNG 往返、ORT 固定图、原应用 DINO 环境与 ORT 小图、
已加载 `.pyd` 的写锁与退出释放、测试包/metadata 更新后的新进程重载、ORT 新进程重载、
外部运行库移除后的 Core 启动。目录包含中文和空格。每个进程的唯一 `python312.dll` 均来自
Core，精确版本 3.12.10、SHA256 `9a0e3435aaa680d868150f87ab3e388ad2eebc22f87e036155c7b4eda8cd2120`。
未观察到越界普通模块、计算/Qt DLL 或 Python 网络调用；Core 与共享运行库载荷在矩阵前后
保持字节一致。Windows `.pyd` 写锁返回错误 32，进程退出后恢复写权限，测试未写入文件。

runner 无 NVIDIA 驱动和可用设备，未做实际 CUDA 运算。DINO 仍仅验证原应用环境检查和
独立 ORT 小图；完整业务模型、worker 协议、产品 GUI、模块安装/更新/恢复均未在这次
诊断实验中验收。11,428,113 字节的 `VisionWorkshopProbeCore.zip` 是诊断入口，
**不是新的产品小包**。本结果允许继续实现正式 Core/模块布局与离线管理，不能勾选整个 B2
或宣称模块化产品已完成。同一提交的 portable 测试运行 45585365072 亦成功。

后续正式 Core、独立模块 ZIP 与产品 EXE 验收使用
[单独的候选构建路径](../visionworkshop-modular-candidate.md)，其结果不与本诊断实验混用。

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

## 首轮真实 Windows 结果

[运行 45575679761](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45575679761)
绑定打包提交 `2dbd6c13423f926c5998d3c16850b731ac8f9f0e`，结果为 **FAIL**，没有通过 B2。
Core 已实际启动，但后续来源校验发现两个需要修正的问题：

1. PyInstaller CArchive 的 `struct` 和四个 `pyimod` 引导模块使用相对 `__file__`。
   验证脚本错误地把这些内嵌模块解析成工作目录中的源码。修正须由真实 EXE 的 CArchive
   清单佐证其身份，不允许将工作目录或任意相对导入加入白名单。
2. 编译阶段继承的 runner PATH 导致 PyInstaller 从 runner 的 Java 安装目录采集 43 个
   UCRT/API-set 文件，合计 2,316,216 字节，其中 UCRT 已实际加载。下一轮须隔离编译时
   PATH 并验证原生输入来源；仅隔离运行时 PATH 不足以保证构建来源可重复。

首轮 CPython ABI forwarder、VCRT140 和 VCRT140_1 的来源、目标摘要及实际加载位置
一致，Python 为精确 3.12.10。尚未运行到外置依赖矩阵，不能根据这次 Core 启动推断
Torch、ORT、模块重载或 GPU 通过。失败报告保留在 artifact `15004042782`，其 ZIP SHA256
为 `4e8ae9298ec88306abe6fc071b98ea667faf2fc7a1c8668f2e6ec69156785fa8`。

## 首轮问题修复与本地验证

修复保留原有来源边界，不将工作目录或任意相对路径加入白名单：

- 构建后使用固定 PyInstaller 6.18.0 的 `CArchiveReader` 读取真实 EXE，记录文件大小、
  SHA256、CPython ABI，以及五个引导模块的归档类型、代码文件名和解压后 payload SHA256。
- 冻结进程从自身 EXE 独立读取同一归档，核对引导模块未被替换；宿主校验其报告与构建后
  清单一致。普通模块仍必须提供 Core、外部运行库或获准第一方源码范围内的绝对来源。
- 编译时 PATH 仅包含本次 CPython、其 DLL 目录和 Windows 系统目录；额外核对 Analysis
  中每个原生输入的真实来源。来自 runner Java 或其他工具安装目录的输入直接报错。
- 显式先加载 Core 自有的 `vcruntime140.dll` 和 `vcruntime140_1.dll`，再加载已固定摘要的
  MSVCP 与 Qt/计算库；实际进程报告核对 VCRT 来源。检测到 GPU 设备但 Torch 无法使用时
  记录失败，不能再归为无硬件未执行。

本地 14 项定向测试通过，包括首轮来源误判、新增 CArchive 证据绑定、普通相对导入拒绝、
Java 来源拒绝和归档截断。全量运行 457 项，450 项通过、6 项平台跳过、1 项失败：
`test_dry_run_previews_body_without_writing_outputs` 的目录不变断言观察到临时测试仓库
`.git/objects/maintenance.lock` 消失，与首轮已有环境现象相同。定向复跑该用例及其
`load_tests` 同组的 5 项，共 6 项通过；未删除、修改或放宽该断言。
Python 语法与工作流 YAML 解析通过。这些均为验证脚本测试，
修正后的真实 Windows 运行尚待重新执行，不能据此将 B2 或产品模块化标记为通过。

归档结构对照固定版本
[PyInstaller 6.18.0 CArchive reader](https://github.com/pyinstaller/pyinstaller/blob/v6.18.0/PyInstaller/archive/readers.py)。

## 第二轮：Core 已通过，发现 TorchVision wheel 的 Python 副本

[运行 45579575542](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45579575542)
绑定 `81e4946144d7a3e6217eeb913dd366016c1f6f96`。真实 `core-without-runtime` 为 **PASS**，
29 个原生输入均来自已批准来源，Java 污染已消除；随后复制运行库时拒绝
`torchvision/python312.dll`，本轮仍是 **FAIL**，尚未运行外置计算矩阵。

重新下载 pip 回执指向的官方固定 TorchVision wheel，核对完整 SHA256 后检查其 RECORD、
DLL PE 结构与消费者。详见[原始静态审计](visionworkshop-torchvision-python-owner-20261125.json)。

| 内容 | 实际结果 |
| --- | --- |
| TorchVision wheel | `torchvision-0.25.0+cu128-cp312-cp312-win_amd64.whl`，9,632,349 字节 |
| wheel SHA256 | `068e519838b4a8b32a09521244b170edd8c2ac9eeb6538b7bf492cd70e57ebf5` |
| 自带 Python DLL | AMD64 / CP312，产品版本 **3.12.12**，7,470,920 字节 |
| 自带 DLL SHA256 | `3436d46bb65a87ba3d215df065f010d9fdab18c994caa275b546b8877b5205b2` |
| Core 唯一 Python DLL | AMD64 / CPython **3.12.10**，6,945,272 字节 |
| Core DLL SHA256 | `9a0e3435aaa680d868150f87ab3e388ad2eebc22f87e036155c7b4eda8cd2120` |

Core DLL 与官方 3.12.10 embeddable ZIP 中的 DLL 完全一致，也与第二轮 CI 的原生输入摘要
一致。TorchVision `image.pyd` 导入的 97 个 Python 符号均由该 Core DLL 提供；这只证明静态
符号闭包，不替代真实图像运算。`_C.pyd` 本身没有直接导入 Python DLL。

修复只允许省略上述**精确路径、发行版本、wheel 来源/摘要、RECORD、DLL 字节/PE/版本**
均匹配的副本。Core 必须提供已选的 AMD64 3.12.10，并重新核对 `image.pyd` 的 Python 导入
全部可解析。省略记录保留副本与 Core 两侧的来源、大小、SHA256、版本、理由和消费者。
其他 Python EXE/DLL、未知副本或异 ABI 仍直接拒绝，没有通用忽略规则。

冻结验收增加 TorchVision PNG 编码/解码往返，并要求实际进程仅加载**一份** Core 内的
`python312.dll`，同时记录其 SHA256。16 项定向测试与使用真实固定 wheel 的静态资格检查
通过；尚待下一轮 Windows 真实运算，不记为 B2 整体完成。

### 第三轮：已安装 RECORD 的路径别名

[运行 45582001546](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45582001546)
绑定 `4c707301a5e4fae8def1c9bf4f75fbfce4a9b528`。Core 无模块启动继续通过，但资格检查在
复制阶段拒绝已安装 RECORD。原因是本 wheel 的原始 RECORD 使用反斜杠；pip 保留原有的
正确摘要记录，同时添加同一文件的斜杠路径、空摘要/大小记录。使用真实 Windows wheel
执行 pip 安装已复现，且与固定
[pip 25.0.1 的安装记录逻辑](https://github.com/pypa/pip/blob/25.0.1/src/pip/_internal/operations/install/wheel.py)
一致。这不是 DLL 字节或 ABI 变化。

资格检查现只核对该单文件：一个正确摘要记录，允许附带一个标准斜杠空摘要别名；矛盾
摘要、额外重复记录、未知解释器及实际 DLL 字节/PE 变化仍拒绝。不比较整份安装 RECORD，
不限制 pip 正常生成的 INSTALLER、入口脚本或 pyc 条目。16 项定向检查通过；使用真实 pip
安装后的 wheel 和 Core DLL 执行资格检查通过。此后把输入资格预检放到冻结编译之前，
并在依赖准备成功后立即保存下载缓存，避免后续验收失败丢失缓存而重复下载。

### 第四轮：外置原生运算通过，补充 Torch 动态命名空间来源

[运行 45583434693](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45583434693)
绑定 `d8666d31b8c3a478e631f430b77d37500e2fbf3f`。Core、外置纯 Python/metadata、
NumPy/psutil/Qt 原生矩阵均通过。`torch-external.json` 的 Torch CPU 矩阵、TorchVision NMS、
PNG 原生编码/解码均为 PASS；但进程最终来源记录拒绝 `torch.ops` 与 `torch.classes`，因此
本轮整体仍为 FAIL，ORT、DINO 和重启矩阵尚未执行。runner 未提供 NVIDIA 驱动，GPU NOT_RUN。

这两个对象由固定 Torch 2.10 自行创建，分别是
[`_Ops`](https://github.com/pytorch/pytorch/blob/v2.10.0/torch/_ops.py) 和
[`_Classes`](https://github.com/pytorch/pytorch/blob/v2.10.0/torch/_classes.py) 的单例；它们的
`__file__` 是人为设置的 `_ops.py` / `_classes.py`，不是工作目录中的文件。
来源记录现仅针对这两个名称核对实现类、实现模块和 Torch 属性的**同一对象身份**，以及
实现文件确实位于外置 `torch` 目录，单独报告为 `generated_module_origins`。普通模块仍要求
真实绝对来源，不把工作目录加入允许范围。17 项定向检查通过，下一轮继续完整冻结矩阵。

## 后续依赖

实验结果用于确定 A4/B3 的模块布局与公共依赖归属，再实现 A5/B4 的离线安装、更新、
卸载与恢复。完整产品仍需接入模块缺失能力判定、外置 DINO DLL/身份清单、新模块协议
与资源定位；保留旧协议 3 的完整包通道。未执行项不能因实验通过而自动勾选。
