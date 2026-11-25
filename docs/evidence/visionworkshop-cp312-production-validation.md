# VisionWorkshop CP312 生产构建验证

由 ChatGPT 记录。验证应用固定为
`jsdfhasuh/emo-vision-train@bb3772003f0b8cbd872d9342a48aa4a82d5bb861`；
构建与验证均为非发布操作，没有创建正式 Release。

当前状态：`673273a` 的真实冻结 CNN PatchCore 人工 CKPT 数值与重载验收已通过，
同一包的 DINO worker 初始化失败。复用原包的 A/B 诊断已证实 MSVCP 加载顺序问题；
正式 runtime hook 修复后的冻结验收仍待新的完整构建。完整 ZIP 的发布尺寸门槛仍阻断。

## 首次生产路径实测

打包器：`f8ba210d876220f49c4a1d33fb1e85366e36ccad`。

- [双平台打包器测试 45524476006](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524476006)：Ubuntu、Windows 通过；Windows 429 项 unittest 通过，并完成真实 fixture 编译、解包、图标及启动测试。
- [Windows 生产构建 45524514970](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524514970)：使用干净 CPython 3.12.10 venv，正式 runtime installer、pip check、实际 imports/P4 CPU 特征计算通过；应用定向回归 400 passed / 1 skipped。
- 固定启动器、主应用和更新器三个 EXE 均编译成功，冻结静态检查通过；随后在 ZIP 大小检查失败。
- 构建 ID：`20261125T012914Z-e492fa1bdd8b`。
- [轻量证据 artifact 14985152031](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524514970/artifacts/14985152031) 的下载 ZIP SHA256：`81a570a9eb7961b86d31fd8cf82e65b714b834f0dfe6a34022a92046cd0a7439`。这是报告下载包，不是产品完整 ZIP。

该次旧逻辑在失败清理时删除了超限临时 ZIP，导致后续 stage、真实冻结启动与数值验收
没有运行。不能把编译成功、fixture 通过或源码测试替代为实际产品验收结果。

## 673273a 保留诊断包后的真实冻结验收

打包器：`673273ad204a45cfdc4eac7b89910be1ce42f577`。
[双平台 CI 45532675249](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45532675249)
的 Ubuntu、Windows jobs 均通过。
[Windows 完整重跑 45532992462](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45532992462)
使用正式 CPython 3.12.10 环境，生产 freeze 记录为 PyInstaller 6.18.0 与
pyinstaller-hooks-contrib 2026.0；测试 CI 中的 PyInstaller 6.22 不代表该产品包的编译工具版本。

原包与逐成员统计在[完整诊断 artifact 14989256921](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45532992462/artifacts/14989256921)，
下列 worker、process、fixture 和构建记录在[轻量证据 artifact 14989092684](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45532992462/artifacts/14989092684)。

- 构建 ID：`20261125T024002Z-8dfb1863ee3e`。
- 产品 ZIP：`VisionWorkshop-windows-x86_64-20261125T024002Z-8dfb1863ee3e-full.zip`。
- 产品 ZIP SHA256：`6b0697b1bbfeb1114a15ccefd4ab62f5f6fb3998b98bc3e843ab342328338035`。
- 主 EXE SHA256：`897563301885641ddbdbbdb0b042f69a9de6c3618f0e4f4a206d8e145683f416`。
- 完整安装清单 `files_sha256`：`32101685939ed8a4a6ff9245d38a4592fc986b788340616a8a31a4cbca065c61`。

该次构建在发布尺寸检查仍失败；完整 ZIP、构建记录和 SHA 校验成功后，原包被保留到
`diagnostics/`。`oversize-archive.json` 记录 `status: blocked-size`、`published: false`、
`publishable: false`；没有生成可发布的 `build-summary.json`，没有执行发布 stage 或上传 Release。
临时探针核验该诊断身份后继续运行实际冻结检查，没有覆盖原构建失败状态。

| 检查 | 673273a 实际结果 | 证据文件 |
| --- | --- | --- |
| 正常 launcher 登记与启动观察 | `GUARD_ACCEPTED`、`CREATING_WINDOW`，存活 5 秒 | `frozen-patchcore/launcher-observation.json`、`launcher-trace.json` |
| GUI 正常退出 | `NOT_OBSERVED`；`close_messages: 0`，使用隔离进程强制清理 | `frozen-patchcore/launcher-observation.json` |
| DINO worker inspect | 失败：ORT 原生绑定导入时 DLL 初始化失败 | `frozen-smoke/dino-inspect.stderr.txt`、`frozen-smoke.json` |
| ONNX CPU schema smoke | 真实冻结 ORT session 运行；模型数值资格仍为 `PENDING` | `frozen-smoke/onnx-cpu-worker.json` |
| 人工原生 CKPT → 完整 ONNX | 通过，冻结端严格恢复 CKPT，memory bank SHA 不变 | `frozen-patchcore/ckpt-export.worker.json` |
| CPU 数值比较与最终图新进程重载 | 两个样本均 `PASS` | `frozen-patchcore/onnx-parity.worker.json`、`onnx-reload.worker.json` |

CNN fixture 加载随包固定 WideResNet 权重，使用 `layer2/layer3`、`[7,1536]` 人工
memory bank、两张固定种子的 RGB 图片和 64×64 输入。Python 子进程只生成 fixture；
实际 CKPT 恢复、导出和两次 ORT 比较由三个独立 `VisionWorkshopApp.exe` 进程执行，
PID 分别为 880、5220、4940，三个退出码均为 0，job 与 report 的 phase/run_id 匹配。
数值通过还要求完整样本报告为 `PASS`，并非仅检查退出码。

| 最大绝对误差 | 图 0 | 图 1 |
| --- | ---: | ---: |
| 预处理张量 | 1.3113021851e-6 | 1.0728836060e-6 |
| 原生 CKPT → 稳定图 score | 0 | 7.62939453125e-6 |
| 原生 CKPT → 稳定图 map | 2.288818359375e-5 | 3.0517578125e-5 |
| 稳定图参考 → ORT score | 0 | 7.62939453125e-6 |
| 稳定图参考 → ORT map | 2.3651123046875e-4 | 2.13623046875e-4 |

比较沿用 `atol=1e-5`、`rtol=1e-4`，逐元素条件为
`abs(actual-reference) <= atol + rtol*abs(reference)`。ORT map 的最大容差占用比分别为
0.0279033、0.0258052，均小于 1。两次 verify 都使用 ORT 1.23.2、
`CPUExecutionProvider`、BASIC 优化，逐项误差报告相同；保存的 FP32 输入、score 和 map
形状分别为 `[1,3,64,64]`、`[1]`、`[1,1,64,64]`，全部有限。

最终 `model.onnx` 为 64,824 字节，SHA256 为
`98dbb55f7cd37f8b86caa85ffdacfd4d2c80a3a208703841ca3b279daed39f8f`；
`model.onnx.data` 为 99,415,044 字节，SHA256 为
`6b972152933fe643be440fa00a3692215a6e63acb1c7dcbc82d8727758c97f76`。
新进程从独立重载目录读取与最终清单 SHA 相同的图文件，再与原参考比较；最终部署清单复查通过。
轻量报告没有上传完整 ONNX/CKPT/EXE；此处实际执行证据来自该次 Windows 运行，不能称为
下载报告后又重新执行了一次模型。

`_is_fitted=True` 为人工构造，阈值固定为 1000.0，未做训练或校准。两个参考分数约为
82.2151、81.7092，均远离阈值，不覆盖阈值边界与正负类别切换。业务模型、训练、GPU、
交互 GUI、产品 UI 模型导入及独立 `predict.py` 执行仍为 `NOT_RUN`。

## DINO DLL 加载顺序根因：复用原包的 A/B 诊断

[诊断运行 45543108729](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45543108729)
使用诊断代码 `0a8e676f0923ba3c8f361ec70a0da42d72994fce`，复用上述 `673273a` 完整 ZIP，
没有替换产品 DLL、依赖或 runtime hook。
[轻量诊断 artifact 14990755447](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45543108729/artifacts/14990755447)
下载文件为 238,082 字节，SHA256 为
`12ea9cc3ba3b60db377045e0703dc602f1a92d25225ffed2e15f2437fb84a1a5`。
`dll-diagnostic.json` 中原产品 ZIP 的前后 SHA 相同，均为
`6b0697b1bbfeb1114a15ccefd4ab62f5f6fb3998b98bc3e843ab342328338035`。

原冻结 DINO 进程实际加载了 `PyQt5/Qt5/bin/MSVCP140.dll` 14.26.28720.3。
在匹配的 CPython 3.12.10 控制进程中，ORT core 与 pyd 分别由独立新进程测试：

| 对照 | 显式加载顺序 | 实际 MSVCP140 | ORT core | ORT pyd |
| --- | --- | --- | --- | --- |
| A：`qt-core-first` | Qt5Core → ORT | Qt 目录 14.26.28720.3 | WinError 1114 | WinError 1114 |
| B1：`root-msvcp-qt` | 仅预载运行时根目录 MSVCP140 → 相同 Qt5Core → 相同 ORT | `app/_internal` 14.40.33810.0 | `TARGET_LOADED` | `TARGET_LOADED` |

A/B 初始均未加载 `MSVCP140.dll`，`preload_failures` 均为空。两组使用相同的 Qt5Core
和 ORT 二进制，SHA 与原 build record 一致；控制进程初始 `VCRUNTIME140.dll` 与随包根目录文件
内容相同。唯一新增的显式预载是随包根目录 MSVCP140；测试后 Torch Python 未导入，
报告无 `evidence_error`。这些控制变量与原 EXE 的加载记录共同证实：该包中先加载 Qt
携带的旧 MSVCP 会导致随后 ORT 初始化失败，预先选择已随包的较新 MSVCP 可改变这一结果。
证据为 `dino-inspect.process.json`、`matrix-qt-core-first-{core,pyd}.json` 和
`matrix-root-msvcp-qt-{core,pyd}.json`。

生产修复限定为 Windows 冻结 DINO 入口在 Qt 初始化前，以绝对路径预载已有的
`app/_internal/msvcp140.dll`，继续避免导入 Torch Python，并跳过原有四项 Torch native 预载。
**A/B 通过是 DLL 加载根因与修复方向证据；正式 hook 修复后的 DINO worker、CPU 数值和
完整冻结验收仍待新的完整构建，不提前标为 PASS，也不改写 673273a 的历史失败。**

## 真实体积与发布边界

| 项目 | 字节 |
| --- | ---: |
| 旧 v1.0.39 完整 ZIP | 2,127,212,894 |
| f8 首次构建 45524514970 的 ZIP | 2,715,520,634 |
| 673 重跑 45532992462 的 ZIP | 2,715,519,943 |
| 既有发布资产上限 | 2,147,483,647 |
| 673 重跑超出 | 568,036,296 |
| 673 与旧版 ZIP 差额 | 588,307,049 |

两次 CP312 构建实际使用 ZIP/LZMA、最高压缩等级和 256 MiB 字典。673 包需要减少
20.918% 才能满足既有上限。旧版本只剩 20,270,753 字节余量。

### 首次构建的原始体积比较

对旧版公开 app 清单与 f8 首次 build-record 的 app 清单做路径归一化比较，排除清单自列文件：

| 目录 | 原始字节增量 |
| --- | ---: |
| 整个 app | +774,586,386 |
| torch | +720,799,009 |
| 其中 torch/lib | +716,919,104 |
| transformers | +41,055,367 |
| onnxruntime | +17,904 |
| PyQt5 | −3,072 |
| static | 0 |

Torch 占 app 原始增量的 93.06%。模型目录中的 13 个文件与旧版大小、SHA256 相同，
其中有 8 项模型/权重，其余为许可证、说明和 metadata，不能称为 13 个模型。
首次完整构建记录按 `(sha256, size)` 分组的全部冗余副本只有 2,001,799 原始字节；
其中 DLL 加载路径和资源别名也不能未经验证删除。相似名称的 NVRTC DLL 内容并不相同。

这些原始字节统计与以下实际压缩统计使用不同分母，不能混用。

### 旧新 ZIP 逐成员压缩实测

[旧 v1.0.39 发布包](https://github.com/jsdfhasuh/emo-vision-train-release/releases/tag/v1.0.39)
的构建 ID 为 `20261120T063559Z-c2865e86f235`。旧包使用真实 ZIP central directory
中的成员压缩长度；新包使用上述完整诊断 artifact 中实际生成的 `archive-members.json`。
本次分析记录按 `VisionWorkshop/` 安装根归一化路径，排除目录条目，逐项求和得到下表，
并记录输入 JSON 的 SHA。旧包全部 payload 未下载重算 SHA，其完整包 SHA 来自 GitHub asset API。

| 分组 | 旧压缩字节 | 673 压缩字节 | 增量 |
| --- | ---: | ---: | ---: |
| Torch | 1,274,783,032 | 1,842,001,613 | +567,218,581 |
| 其中 Torch/lib | 1,266,687,343 | 1,832,806,218 | +566,118,875 |
| 其中明确列出的 CUDA/NVIDIA DLL 子集 | 1,216,956,956 | 1,780,413,175 | +563,456,219 |
| 模型目录 13 个文件 | 396,641,352 | 396,641,352 | 0 |
| ONNX Runtime | 97,240,288 | 97,246,299 | +6,011 |
| PyQt5 | 79,077,996 | 79,077,583 | −413 |
| Transformers 文件目录 | 0 | 8,155,932 | +8,155,932 |

Torch/lib 和 CUDA/NVIDIA 子集均包含在 Torch 中，不能叠加求和。Torch 压缩负载增加
567,218,581 字节，占 ZIP 总增量的 **96.4154%**。ZIP 文件负载增量为 587,728,301
字节，结构开销另增加 578,748 字节，两者合计 588,307,049 字节。

即使按当前成员数据扣除整个模型目录的 396,641,352 压缩字节，仍超限 171,394,944
字节（约 163.455 MiB）；即使再假定全部 ZIP 结构开销为零，仍超限 167,579,882 字节。
这是反事实算术，不是重建后的压缩测量或已经实施的拆包方案。`torch_cuda.dll` 的原始
大小减少 19,764,736 字节，实际压缩负载却增加 42,689,396 字节，也说明原始体积不能
用于推导压缩收益。当前未实施模型/CUDA 拆包、外置安装、更新协议变化或依赖版本降级。

## 正式修复后的待验证项

新的完整构建需重新记录修复提交、工具链、build ID、ZIP SHA/大小，并分别运行已有的
启动观察、DINO worker、CPU schema、人工原生 CKPT 导出/数值比较/最终图重载检查。
新的结果必须绑定新的实际产物；本记录的 673273a CPU 成功与 A/B 原生加载成功不替代
修复后产物的正式验收。

发布与 stage 继续遵守 2,147,483,647 字节上限；超限诊断保留仍使原构建失败，不生成
可发布摘要、不上传 Release。DINO 初始化修复和发布体积是两项独立问题。
真实业务模型、GPU、交互式 GUI、GUI 正常退出、训练和断电更新等未执行或未观察到的项目，
继续按各自实际状态记录，不填写为完整产品验收通过。
