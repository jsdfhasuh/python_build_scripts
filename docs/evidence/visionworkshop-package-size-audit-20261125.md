# VisionWorkshop 包体积与模块化缩减审计

由 ChatGPT 于 2026-11-25 根据实际 ZIP 成员账本、构建清单、应用源码和既有模块化计划核对。
本报告只补充分析与实施优先级，没有构建新的 CPU/Core 包，没有删除 DLL、模型或产品能力。

## 1. 结论与当前缺口

当前 2,715,516,448 字节的产物仍是完整 GPU 便携包。统一 CPython 3.12、延迟初始化后端、
DINO worker 避免导入 Torch，并没有实现按功能独立分发、安装和更新。

用户此前确认的目标确实包含模块化离线发布，而不只是延迟加载：预先下载模块 ZIP，
现场断网安装；所有本地模块共用同一 CPython 和一致依赖，不为每个功能复制 Python/Torch。
已有 [应用设计](https://github.com/jsdfhasuh/emo-vision-train/blob/a2278252a5a1ff7d6426ac7cf72c6f5584642ad9/openspec/changes/unify-python-runtime-and-modular-distribution/design.md)
及 [打包配套计划](https://github.com/jsdfhasuh/python_build_scripts/blob/docs/unify-python-runtime-modular-release/docs/plans/unify-python-runtime-and-modular-distribution.md)。

应用计划分支的清单仍未同步最近的 CP312 修复；不能仅凭未勾选任务认定没有实际进展。
但实际产品仍没有正式模块安装器、模块文件注册表或独立模块更新路径，打包端也没有按功能
选择资产。当前完成的是统一运行时的一部分及限定范围的冻结验收，模块化交付尚未完成。

**最大缩减机会是 GPU 运行库与预置模型的按需分发。** 已识别的 Torch/ORT GPU DLL
占当前 ZIP 的 68.82%，预置模型目录占 14.61%。小文件清理和全文件去重不足以解决当前
568,032,801 字节的超限。

## 2. 数据身份与统计口径

| 项目 | 值 |
| --- | --- |
| 应用提交 | `bb3772003f0b8cbd872d9342a48aa4a82d5bb861` |
| 实际产品打包器提交 | `a63f320f86ca6dbfaf48d57afbd9853b8333ddc2` |
| 完整构建 | [45544329988](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45544329988) |
| 构建 ID | `20261125T041832Z-524aee200c44` |
| 产品 ZIP 大小 | 2,715,516,448 字节 |
| 产品 ZIP SHA256 | `186b9c02076b02c017f0e84203740d53bff8efa1b820da6cb4a32503b653ae90` |
| 解压后文件内容合计 | 6,371,667,282 字节，13,174 个文件 |
| 轻量证据 | [artifact 14993523793](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45544329988/artifacts/14993523793) |
| 逐成员原始数据 | 上述 artifact 的 `archive-members.json` |
| 本次派生明细 | [size-audit JSON](visionworkshop-package-size-audit-20261125.json) |

下文 MB/GB 采用十进制，MiB 采用 1,048,576 字节。体积为 ZIP 中各成员实际压缩字节；
第 3 节主分组互不重叠，另列 ZIP 结构开销。不是安装环境中 wheel 的下载大小，也不是原始 DLL
大小。GPU 分类按列出的 Torch/ORT DLL 文件名归组，不等于已证明完整运行依赖闭包。

## 3. 2.716 GB 具体装了什么

| 内容 | 实际压缩字节 | 约 MB | 占完整 ZIP |
| --- | ---: | ---: | ---: |
| Torch CUDA/NVIDIA DLL，27 个 | 1,780,413,175 | 1,780.41 | 65.56% |
| ORT CUDA/TensorRT provider DLL，2 个 | 88,523,212 | 88.52 | 3.26% |
| 预置模型目录，含配套许可与元数据 | 396,641,352 | 396.64 | 14.61% |
| 其余程序、依赖、资源及 ZIP 结构 | 449,938,709 | 449.94 | 16.57% |
| 合计 | 2,715,516,448 | 2,715.52 | 100% |

GPU 两项合计 **1,868,936,387 字节**。其中仅 `cublasLt64_12.dll` 压缩后就有
370,276,594 字节，`torch_cuda.dll` 为 316,280,724 字节，
`cudnn_engines_precompiled64_9.dll` 为 232,036,256 字节。

“其余”仍包含与 CUDA 链接的 TorchVision 扩展、CPU 相关库和算法依赖，不能将其直接
命名为已验证 CPU/Core 包。三个应用 EXE 合计约 131.09 MB，整个 PyQt5 目录约
79.08 MB；当前不是 Python 业务源码占据主要空间。

### 预置模型可按用途分配资源包

| 资源组 | 实际压缩字节 | 约 MB |
| --- | ---: | ---: |
| CNN PatchCore 预训练权重及配套说明/元数据 | 248,203,193 | 248.20 |
| 图片精简 DINOv2 权重及许可/说明 | 80,620,719 | 80.62 |
| EdgeSAM 编码器、解码器 | 35,503,957 | 35.50 |
| 四个 YOLO 预置模型 | 32,313,483 | 32.31 |
| 合计 | 396,641,352 | 396.64 |

模型目录的 13 个文件实际是 8 个模型/权重文件和 5 个配套文件。将它们放入相应功能的
离线资源包不等于取消这些功能；需要该功能的机器仍提前获得对应权重，现场不自动联网下载。
是否必需某个权重，应按具体模型加载/训练路径验证，不能仅按文件扩展名删除。

## 4. 为什么比旧版又增加了约 588 MB

旧 v1.0.39 ZIP 中实际存在 `torch-2.5.1+cu121.dist-info` 和
`torchvision-0.20.1+cu121.dist-info`。新 ZIP 和 `production-freeze.txt` 对应
`torch==2.10.0+cu128`、`torchvision==0.25.0+cu128`。
这次同时更换了 Torch/CUDA 分发组合，不能把增长解释为 Python 3.12 本身的必然开销。

| 文件 | 旧压缩字节 | 新压缩字节 | 增量 |
| --- | ---: | ---: | ---: |
| `cublasLt64_12.dll` | 205,179,084 | 370,276,594 | +165,097,510 |
| `cufft64_11.dll` | 45,181,429 | 142,445,962 | +97,264,533 |
| `cusparse64_12.dll` | 105,122,459 | 157,193,910 | +52,071,451 |
| `cusolver64_11.dll` | 44,633,319 | 93,158,730 | +48,525,411 |
| `torch_cuda.dll` | 273,591,328 | 316,280,724 | +42,689,396 |

全部 Torch 目录的压缩增量为 567,218,581 字节，占新旧 ZIP 总增量 588,303,554 字节
的 96.4160%。没有独立验证编译架构、PTX 或内核覆盖如何贡献增长，因此不作进一步归因。
旧版比较来自其真实 ZIP central directory，并非重新下载和校验了旧完整载荷，方法见
[生产构建验证](visionworkshop-cp312-production-validation.md)。

## 5. 当前源码为什么仍会生成完整包

打包器以下路径均对应实际产品提交 `a63f320`：

- `ci/vision-train-runtime.json` 选择完整 CUDA 12.8 的 Torch/vision/audio 组合，
  并声明需要完整 CUDA DLL、ORT GPU 和预置模型。
- `configs/emo-vision-train.json` 将 Torch、ONNX、DINO 等同时加入 hidden imports，
  完整收集 Torch/vision binaries，并将 `static` 等目录加入数据。
- `build.py` 根据 hidden imports 自动补充 Torch/vision binary 收集。
  只删 JSON 中一项 `collect_binaries` 仍会被加回。
- `portable_release.py` 压缩整个产品目录，没有 Core/runtime/model 的独立产物选择。
- `vision_train_runtime.py` 的完整包校验要求上述 DLL 与模型存在，不能通过删文件绕过。

应用已有的 [P7 延迟加载](https://github.com/jsdfhasuh/emo-vision-train/blob/bb3772003f0b8cbd872d9342a48aa4a82d5bb861/docs/evidence/patchcore-p7/lazy-backend-20261001.md)
只在使用时初始化后端，改善启动与内存行为；该报告本身明确是源码验收，没有构建 EXE。
DINO worker 不导入 Torch Python，但它的 GPU 路径仍从冻结包 `torch/lib` 取 CUDA DLL。

独立功能边界还需适配：现有 YOLO 实现仍导入 Torch，不能把所有 YOLO ONNX 路径直接
视为纯 ORT；图片精简依赖 Torch/timm/safetensors；Kaggle 客户端有主界面顶层导入。
轻 Core 必须允许这些可选能力缺失而正常启动，并保留已有功能的完整依赖声明。

## 6. 缩减空间：可量化的部分与尚未实测的部分

以下仅从当前 ZIP 扣除现有成员压缩字节，保留现有 ZIP 结构开销；不是重新构建结果。

| 测算 | 余下字节 | 约 MB | 含义 |
| --- | ---: | ---: | --- |
| 只移出模型目录 | 2,318,875,096 | 2,318.88 | 仍超上限 171,391,449 字节 |
| 移出已识别 Torch/ORT GPU DLL | 846,580,061 | 846.58 | 显示 GPU 分发边界的主要价值 |
| 再移出模型目录 | 449,938,709 | 449.94 | 量级参考，不是可运行 Core 大小承诺 |

当前 CUDA 版 Torch 不能通过删除 CUDA DLL 变为 CPU 版。若增加无 GPU 的 Torch 运行库
选项，应使用匹配的官方 CPU wheels 重新构建和验证。官方提供同版本 Torch 2.10.0 /
TorchVision 0.25.0 的 CPU 和 CUDA 分发，因此无需先假定必须降级 Python 或 Torch；
但本项目的 CPU 变体尚未实测。

参考：[PyTorch 官方版本组合](https://pytorch.org/get-started/previous-versions/)。
CPU/GPU 运行库变体的锁身份、替换与兼容合同还需设计；每个 import namespace 只能有
一个实际归属，不将两套 Torch 混装，也不为每个算法再带 Python。ORT CPU/GPU 发行包
同样应避免混装，参考 [ORT 官方安装说明](https://onnxruntime.ai/docs/get-started/with-python)。

### 模块化会缩小哪些东西

- Core 默认包、只需部分功能机器的下载量与安装占用。
- 不变运行库/权重无需重复交付时的后续更新量。
- 每个独立发布资产，避免所有能力挤入一个超过现有限制的 ZIP。

安装全部功能、全部 GPU 库和全部权重时，总体积不会因拆成多个 ZIP 自动消失。
不要将 450 MB 的算术余量宣称为全部功能可用的安装大小。

## 7. 不值得作为主方案的清理

| 已核对的候选类别 | 当前压缩字节 | 说明 |
| --- | ---: | --- |
| 全部 tests/test/testing 路径 | 799,906 | 仍需确认是否有运行时引用 |
| 全部 examples 路径 | 24,120 | 很小 |
| 头文件 | 13,868 | 很小 |
| `.lib/.a` | 35,254 | 很小 |
| Qt QML | 6,625,378 | 未证明全部可删 |
| Qt 翻译 | 5,177,686 | 可按实际语言需求审查 |
| WebEngine devtools 资源 | 1,693,971 | 先确认相关功能 |
| TorchAudio | 1,118,313 | 另有 8,379 字节元数据；需产品调用审查 |
| 全文件同 SHA 去重理论上限 | 557,851 | 不包括 EXE 内嵌归档，且相同内容仍可能要求不同路径 |

当前实际包中没有大量 `.pdb`、`.pyc`、Torch headers/include、Qt Designer 开发工具、
pytest 或 pip 可供删除。这些工具可能出现在构建环境，不能据此认为它们都进入了发行包。
Torch 的 `nvrtc64_120_0.dll` 和 `.alt.dll` SHA 与大小不同，不能因为名字类似就当成重复文件。

现用 ZIP/LZMA 与 256 MiB 字典。没有新的压缩格式重建对比，不能承诺改成 7z 或继续提高
压缩参数就能省掉 568 MB。改压缩格式还涉及分发/解压兼容；主要工作应先处理内容归属。

## 8. 沿已有计划实施的顺序

1. **真实冻结 Core 外置模块加载实验（B2/D6）。** 用唯一 CP312 验证外部 Python、
   `.pyd`、DLL、包元数据、Torch/ORT、空格/中文路径、重启与文件锁。
   当前完整包验收不能替代此项；实际 GPU 运算与 CPU 运算分开记录。
2. **确定共享运行库归属与模块构建目标（A4/B3）。** Core、公共运行库、YOLO、PatchCore、
   ONNX、DINOv2、Kaggle/图片精简及模型资源复用一致依赖；公共包只有一份。
   由实测决定 CPU/GPU runtime 变体或共享组件的具体边界。
3. **实现离线模块生命周期（A5/B4）。** 本地 ZIP 的兼容与摘要检查、暂存、释放相关
   worker/DLL、激活、失败恢复、更新和卸载；不要求现场联网、pip 或外部 Python。
4. **量化最终包并联合验收（B5）。** 比较实际 Core/选配模块的 ZIP、解压占用和更新量；
   验证未装可选模块时 Core 可用，模块更新不修改其他模块与 Core，缺失硬件明确 NOT_RUN。

既有设计 D9 要求协议 3 保持不变；新模块版使用新 schema 与新安装目录，首版不进行
协议 3 的原地转换。当前协议 3 的顶层布局和完整目录摘要不支持简单挪出几个目录，
应新增模块通道，不临时放宽旧包完整性规则。

本次未改产品代码、未删除功能、未实施拆包、未发布 Release，也未将这些分析计为新包验收。
