# VisionWorkshop CP312 生产构建验证

由 ChatGPT 记录。验证应用固定为
`jsdfhasuh/emo-vision-train@bb3772003f0b8cbd872d9342a48aa4a82d5bb861`；
构建与验证均为非发布操作，没有创建正式 Release。

## 首次生产路径实测

打包器：`f8ba210d876220f49c4a1d33fb1e85366e36ccad`。

- [双平台打包器测试 45524476006](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524476006)：Ubuntu、Windows 通过；Windows 429 项 unittest 通过，并完成真实 fixture 编译、解包、图标及启动测试。
- [Windows 生产构建 45524514970](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524514970)：使用干净 CPython 3.12.10 venv，正式 runtime installer、pip check、实际 imports/P4 CPU 特征计算通过；应用定向回归 400 passed / 1 skipped。
- 固定启动器、主应用和更新器三个 EXE 均编译成功，冻结静态检查通过；随后在 ZIP 大小检查失败。
- 构建 ID：`20261125T012914Z-e492fa1bdd8b`。
- [诊断 artifact 14985152031](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45524514970/artifacts/14985152031) 的下载 ZIP SHA256：`81a570a9eb7961b86d31fd8cf82e65b714b834f0dfe6a34022a92046cd0a7439`。

该次旧逻辑在失败清理时删除了超限临时 ZIP，导致后续 stage、真实冻结启动与数值验收
没有运行。不能把编译成功、fixture 通过或源码测试替代为实际产品验收结果。

## 真实体积与边界

| 项目 | 字节 |
| --- | ---: |
| v1.0.39 完整 ZIP | 2,127,212,894 |
| 本次完成压缩的 ZIP | 2,715,520,634 |
| 既有发布资产上限 | 2,147,483,647 |
| 本次超出 | 568,036,987 |

本次实际使用 ZIP/LZMA、最高压缩等级和 256 MiB 字典。需要减少当前压缩包的
20.918% 才能满足既有上限。旧版本只剩 20,270,753 字节余量。

对旧版公开 app 清单与新 build-record 的 app 清单做路径归一化比较，排除清单自列文件：

| 目录 | 原始字节增量 |
| --- | ---: |
| 整个 app | +774,586,386 |
| torch | +720,799,009 |
| 其中 torch/lib | +716,919,104 |
| transformers | +41,055,367 |
| onnxruntime | +17,904 |
| PyQt5 | −3,072 |
| static | 0 |

Torch 占 app 原始增量的 93.06%。全部 13 个离线模型文件与旧版大小、SHA256 相同。
新完整构建记录按 `(sha256, size)` 分组的全部冗余副本只有 2,001,799 原始字节；
其中 DLL 加载路径和资源别名也不能未经验证删除。相似名称的 NVRTC DLL 内容并不相同。

这些是清单原始字节统计，不能冒充逐成员压缩贡献或保证可节省的压缩字节。
重跑时的 `archive-members.json` 将记录真实 ZIP 中每个成员的压缩与原始字节。
当前未实施模型/CUDA 拆包、外置资源安装、客户端更新协议变化或依赖版本降级。

## 后续实测要求

超限诊断保留必须继续让原构建失败，发布与 stage 上限保持不变；只有完整 ZIP 与构建
记录校验成功才允许保留。临时探针可在明确识别这类失败后单独进行冻结验收并上传诊断
artifact，不能把原失败状态覆盖为发布成功。

实际冻结验收需分别记录启动观察、DINO worker、CPU schema、人工原生 CKPT 完整 ONNX
导出、逐样本数值比较和最终图的新进程重载结果。真实业务模型、GPU、交互式 GUI、训练
和断电更新的未执行项仍应明确标注。后续运行结果将以独立构建身份追加在本记录中。
