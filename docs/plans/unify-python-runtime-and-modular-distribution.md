# Vision Workshop 统一 Python 3.12 与模块化发布 — 打包仓库配套计划

状态：B2 的 CPU 外置加载限定场景已验证，完整 B2 门禁未闭合；首次产品候选构建 BUILT、验收 FAIL，未正式发布。  
打包基线：`master@702fca523be0aae306763cde6f19742a96c4a0cb`。  
应用基线：`main@39ee980f8179e81d1ad90cafcec1e65d3b944c81`。  
对应应用 OpenSpec：[`unify-python-runtime-and-modular-distribution`](https://github.com/jsdfhasuh/emo-vision-train/tree/docs/unify-python-runtime-modular-release/openspec/changes/unify-python-runtime-and-modular-distribution)。

## 2026-11-25 实施状态补充（按实际证据更新）

计划制定时状态为“计划草案，未实施”；上方两个提交基线以及第 2 节为历史快照，予以保留。原文档分支为 `docs/unify-python-runtime-modular-release@50ebccf9a0f0d1b9afa4e530f6ea3bdc9d6e78ee`。原任务句子、编号和跨仓库 Gate 不变；勾选有逐项真实证据的 B2 子项，以及 GPU 未执行状态标记和新协议 schema 的对应实现项；另按首次真实完整候选的构建报告勾选 B3.3、B5.1 和 B5.7；仅代表 manifest 自动生成、Windows 隔离构建及资产大小/哈希报告完成，不关闭产品验收或其他阶段门禁。

| 证据层 | 身份与范围 |
| --- | --- |
| 历史完整包 / PR #4 | `fix/visionworkshop-cp312-runtime-dev-tools@6d4278aa0adddcd45994e64f1bf673886b2037d8`。完整包和体积审计保留为原产物基线，不改写成模块候选结果。 |
| 历史 B2 CPU / PR #6 | [run 45585355615](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45585355615)：builder `b8cd91e9c72a682cd5efce91ac713100601da488`；app `bb3772003f0b8cbd872d9342a48aa4a82d5bb861`；CPython 3.12.10 / PyInstaller 6.18.0；10 个真实 EXE 场景通过，cpu_external_loader PASS / 总体 LIMITED / GPU NOT_RUN。见[B2 固定证据](https://github.com/jsdfhasuh/python_build_scripts/blob/940986d603e4286d7419beb57d6312627233ef29/docs/evidence/visionworkshop-modular-loader.md)。 |
| 完整产品候选实现 | PR #6 的独立 protocol-4 builder、完整文件归属/锁/manifest、Core 与所选模块 ZIP、离线事务驱动已有源码。第一方算法适配器仍随 Core；未实现 Core 升级事务。 |
| 首次完整产品结果 | [run 45616400076](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076)；builder `f9703a9c6a0c0370a10eed0afadd39e677770547`；app `c8c0fbe98a055620ddc5488be6835cf216b4800e`；构建 `BUILT`、产品 `FAIL`。证据 artifact `15028274168`，外层 ZIP SHA256 `409bf843e05c7d408ee32f136ac3e8505997157ef245275764ca595e425ae877`。 |
| 构建与资产身份 | build `candidate-45616400076-1`；Core manifest SHA256 `68bd245e8406b7a9dc2decef653c2d8c556c05aabf702b4b4ae2d5d066e873ae`；完整 lock SHA256 `765b59a43a50ebc1714dccac2cc1f8c12e543031d5673beb6f34cc3e704c0829`；`module-manifests.json` 报告 SHA256 `80a35694001f2e4d1cbecdc17c2c52b4f7d2bc1f435ae9a2b5c3e262dde5aa16`；CPython 3.12.10 / cp312 / win_amd64。当前未生成独立正式模块总索引；原生计算时的实际 CRT 加载尚未验证。 |

历史 B2 probe constraints 是选定子集，不是完整产品 lock；诊断 Core ZIP 也不是产品 Core。新的官方 14.52 CRT 来源、readline 精确归属及本轮扩展 fixture 都必须绑定新候选结果，不追溯记为旧 B2 已验证。

首次完整ZIP已在[run45616400076](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45616400076)完成：app `c8c0fbe98a055620ddc5488be6835cf216b4800e`、builder `f9703a9c6a0c0370a10eed0afadd39e677770547`，build `candidate-45616400076-1`。Core为180,416,446字节、最大Torch包1,865,186,577字节，全部12个ZIP共2,791,206,650字节且单资产未超限。首条真实EXE命令写出了成功状态文件，随后因中文向cp1252重定向输出而退出1；产品报告FAIL、cases为空。证据artifact15028274168，外层SHA256 `409bf843e05c7d408ee32f136ac3e8505997157ef245275764ca595e425ae877`。这份已构建产物保留失败资格；应用 f1557cb1 已修复编码、fa92b087 修正 Windows 测试换行断言，下一候选重新构建Core和运行全部检查。

后续 [run 45633041291](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45633041291) 停在新标准流测试的 Windows 换行断言，未生成新 Core；修正后 [run 45634156750](https://github.com/jsdfhasuh/python_build_scripts/actions/runs/45634156750)（app `fa92b08720726ccf984fdf90d03dc4071a1adf68`、builder `baf33237b9613f69758415ace80f969b0c8a01b4`）通过前置源码检查，下载并验证原 11 个模块 ZIP，随后因新安装库存的 `RECORD` 字节差异被严格复用门拒绝。42,519 个 payload 路径/大小一致，只有 34 个原安装记录的哈希改变，其余文件字节相同；运行时 RECORD 行、准备排除名单和 wheel 来源记录一致。新旧完整 RECORD 的差异仍需逐行证明，不能仅凭此统计放宽校验。本轮没有新 Core 或产品 EXE 结果；证据 artifact `15034115936`（34,697,589 字节），外层 SHA256 `11b7c8d8e200ae55adf82d52045b4e5cdc94e906a3b5aec20389695bdc5fe4ea`。

固定 Ultralytics 上界的来源已核实：2026-01-21 的 [PR #23353 维护者说明](https://github.com/ultralytics/ultralytics/pull/23353#issuecomment-3777012162) 指向当时 Torch 2.10 / ExecuTorch 1.1 发布不同步导致的 ExecuTorch 导出失败；2026-01-28 的 [0537be1](https://github.com/ultralytics/ultralytics/commit/0537be116924fef9ec3a66e4689134a6a59e7dce) 才移除上界并修改 exporter/autobackend。当前固定 `74b2b91` 不含该后续提交。这个原因不证明所有 YOLO 训练/推理均不兼容，也不消除当前原始声明与所选 Torch 的冲突。

生产 DINO 数值验收另缺可用原件：[历史 P5 证据](https://github.com/jsdfhasuh/emo-vision-train/blob/c8c0fbe98a055620ddc5488be6835cf216b4800e/docs/evidence/patchcore-p5/stage-20260927.md) 记录受限 Windows 本机保存的稳定部署 ZIP（SHA256 `5e7f5482ed5f56f68ab02b703293d83ff1e7875f7b0c8a01a88075b67367923e`）、原 `reference.json` 和 88 条 NPZ；当前 workspace/CI 没有这些原件。当前 `resource.patchcore-dino` 仅为预训练骨干，不能替代已训练 memory bank、阈值及独立参考。固定 worker 的 inspect/verify/session 入口和无控制台管道恢复已有源码，新增 [dino-worker 诊断](https://github.com/jsdfhasuh/emo-vision-train/blob/b1201a03313da762cdd2854a0cd1ff4f87ed87b1/docs/evidence/modular-dino-worker-source-20261125.md) 直接使用产品 resolver/client，检查真实父子进程、错误回包、启动后取消和清理；源码 73 项检查、14 项子测试通过，冻结执行仍未运行。成功会话、原模型数值与子进程全程实际导入审计仍分别未验证。针对原目录、文件名和部署摘要的定向检索未找到可用私有输入；不能把预训练骨干当作其替代。

| 完整产品检查 | 当前结果 |
| --- | --- |
| Core-only、真实标注、租约、原生/工作进程、冷 repair/移除/回滚 | NOT_RUN：完整产品在首条 CLI 编码错误处停止，尚无对应 EXE 通过证据。待核对对应真实 EXE 报告与 Core/无关模块前后摘要。 |
| 四类资源及 YOLO 四份原预训练权重 | NOT_RUN：完整产品在首条 CLI 编码错误处停止，尚无对应 EXE 通过证据。待核对每项注册资源来源、实际 CPU 执行和形状/finite 验证；不代表既有业务模型精度。 |
| EdgeSAM 不同 manifest 生命周期 | NOT_RUN：完整产品在首条 CLI 编码错误处停止，尚无对应 EXE 通过证据。待核对新旧版本/manifest 必须实际不同，单模块激活/回滚及无关文件摘要以报告逐项填写；未运行前不得记 PASS；夹具只增加诊断 marker，原模型字节不变，新模型计算 NOT_RUN；无关模块为当时已安装的 ORT。 |

完整候选 lock 由 builder 根据固定 recipe/constraints 与实际 wheel 来源库存生成，再绑定 Core 和各模块；尚未完成 B1.1/.3 所述应用预先批准完整 lock 后由 builder 消费安装的流程。

Core 独立升级、第一方算法代码独立模块、CPU-only wheel 分发、CUDA、生产 DINO worker 的冻结及原数值合同验收、既有业务模型资格、完整协议 3 published update retest、安装中途终止和断电恢复继续未完成。固定 Ultralytics 的 Torch 声明冲突使 Gate A1 保持未闭合；受控 fixture 或 preparation pip check 均不冒称包含该 source vendor 的完整环境资格。

## 1. 目标与边界

将 VisionWorkshop 产品构建从 Python 3.11 迁移到与应用仓库一致的 CPython 3.12 x64 精确补丁版本和 ABI；使用应用仓库生成的唯一完整依赖锁；在真实冻结程序验证通过后，支持 Core、共享运行库和功能模块独立构建、校验和离线发布。

本计划只修改 VisionWorkshop 专用配置、代码路径和工作流。打包仓库还服务其他产品，尤其 EmoMaster 的 Python 3.10 配置和工作流不得被全局升级。

不在本计划中实现算法业务逻辑，不改变 Kaggle 远端 Python 环境，不正式发布，不迁移现有协议 3 用户。

## 2. 计划制定时的实现快照

- `configs/emo-vision-train.json` 当前 `python_version=3.11`，通过 `ci_extra_packages` 补充 TorchVision 和 ORT GPU。
- `ci/vision-train-runtime.json` 当前锁定 Python 3.11、CUDA 12.1、Torch 2.5.1+cu121、TorchVision 0.20.1+cu121、TorchAudio 2.5.1+cu121。
- `vision_train_runtime.py` 负责 GPU wheel 安装、依赖解析、pip check、Torch/CUDA 版本、DLL、模块导入、DINO runtime 和冻结包验证。
- `hooks/vision-train/hook-torch.py` 复用上游 PyInstaller Torch Hook 并保留项目特定 collection mode。
- `pyi_rth_torch_dll.py` 与 runtime validation 处理 Torch/CUDA DLL。
- `portable_release.py`、build records、branding/wizard 和 `visionworkshop-portable.yml` 共同负责输入快照、构建、压缩、资产校验和发布。
- 当前包验证明确要求 `python311.dll`、DINO main runtime 模块、ORT 原生扩展和 Torch/CUDA DLL。
- `visionworkshop-tests.yml` 是打包仓库自身测试环境；其 Python 版本不应因为产品 runtime 统一而全局变更。
- 协议 3 和现有 Core/App/Updater 布局必须继续服务已发布版本。

## 3. 实施任务

### B0 — 只读构建审计

- [ ] B0.1 追踪 VisionWorkshop 从 Release Wizard/CLI 到 build.py、PyInstaller、ZIP 和 Release 的完整调用链。
- [ ] B0.2 核对所有 VisionWorkshop 专用 Python 版本、ABI、CUDA、Torch、ORT、OpenCV 和 Qt 检查。
- [ ] B0.3 核对 `vision_train_runtime.py` 的 requirements 合并规则，确认不会覆盖应用完整锁中的其他依赖。
- [ ] B0.4 核对 Torch Hook、runtime hook、DLL 搜索目录及冻结 worker 启动方式。
- [ ] B0.5 核对 DINO main runtime 和历史 Embeddable 资源检查，区分当前发布路径与兼容测试夹具。
- [ ] B0.6 核对 add_data、hidden_imports、collect_binaries、collect-all、metadata 和静态资源的实际用途。
- [ ] B0.7 获取当前正式完整 ZIP，生成目录/文件/压缩前后体积账本。
- [ ] B0.8 记录其他产品配置和工作流基线，确保本次改动不会影响它们。

### B1 — CPython 3.12 构建环境

> 实施注：已有独立 CP312 构建/准备环境、精确来源回执、依赖闭包及原生文件检查。完整锁、最终 PE/CRT 来源和新产品计算须绑定最终候选；现有 CUDA-enabled Torch 的 CPU 运算不是 CPU-only 分发。

- [ ] B1.1 消费应用仓库批准的精确 Python 3.12 补丁版本和依赖锁身份。
- [ ] B1.2 仅修改 `configs/emo-vision-train.json` 和 `ci/vision-train-runtime.json` 的 VisionWorkshop 配置。
- [ ] B1.3 移除对 requirements.txt 的不透明覆盖/重复解析，改为验证并安装应用仓库的完整锁；如需 GPU 专用 index，明确锁定 wheel URL/hash 和安装顺序。
- [ ] B1.4 更新 `python312.dll`、CP312 .pyd、Torch/CUDA/ORT/OpenCV 原生文件和元数据验证。
- [ ] B1.5 更新 Torch DLL 清单及 CUDA 依赖闭包验证。
- [ ] B1.6 更新 DINO runtime 检查，使其验证统一 CP312 runtime，不再接受第二份 Python 解释器。
- [x] B1.7 保留真实 GPU 未执行时的 NOT_RUN 状态；不能用 DLL 存在或 Provider 名称代替 GPU 运算通过。
- [ ] B1.8 更新 VisionWorkshop 专用 Release workflow 的 setup-python、cache key 和依赖安装。
- [ ] B1.9 不修改其他产品的 Python 配置，也不因产品版本变更而无差别修改通用 tests workflow。

### B2 — 冻结程序外置模块加载技术验证（强制门禁）

> 已核证范围：下方五个勾选只对应 run 45585355615 的原输入。纯 Python/metadata、CP312 扩展、CPU 原生运算、DLL 来源、真实文件锁/退出释放、中文空格路径及测试包更新后重启已执行。B2.4 的卸载指进程退出后的释放与新进程重载，未实现进程内热卸载。B2.5/.6 的 CUDA 未运行；B2.7 的 production_worker_protocol 明确 NOT_RUN，只有 DINO environment() 与 ORT 小图。`dino` 环境/ORT 小图与新增 `dino-worker` 产品父子进程负例生命周期分列；后者尚未冻结执行，即使通过，也不证明子进程完整生命周期的实际导入集合、成功模型会话或原数值合同，因此 B2.7 继续留空。

- [x] B2.1 构建最小真实 PyInstaller onedir Core，绑定精确应用/打包 SHA。
- [x] B2.2 从 Core 外部目录加载纯 Python 包和 distribution metadata。
- [x] B2.3 加载 CP312 .pyd 并验证其依赖扩展和 ABI。
- [x] B2.4 验证模块 DLL 的搜索路径、加载顺序和卸载/重启行为。
- [ ] B2.5 验证 Torch CUDA DLL 只存在一份且能实际执行运算。
- [ ] B2.6 验证单份 ORT GPU 发行包的 CPU Provider 和 CUDA Provider。
- [ ] B2.7 验证 DINO worker 通过产品统一 runtime 启动且不导入 Torch。
- [x] B2.8 验证含空格/中文路径、模块更新后重启和文件锁。
- [ ] B2.9 若外置 .pyd/DLL/metadata 不可靠，停止模块管理器开发并调整打包布局；不得用模拟 sys.path 测试替代。

### B3 — 模块构建与清单

> 实施注：所选 Core/运行库/第三方 feature/资源 targets、单一所有权、完整 lock/manifest、独立 ZIP 及校验已有源码和首次真实构建；MSVCP 固定 Core canonical 与 Qt/scikit-learn 原始副本为显式来源集合，不等于所有 CRT 文件物理单份；实际 ZIP、单资产大小与总量见上方首次构建记录；它们是内部候选，不是正式发布资产。当前有构建摘要和模块 manifest 报告，尚无独立正式模块总索引。B3.3 以首次候选 11 份实际 manifest 的完整字段和绑定身份为据；B3.4 的独立总索引尚未完成，B3.5 的新候选重复文件与完整前后对账尚缺，均不勾选。B3.1 需注明当前模块边界，第一方算法代码仍在 Core；B3.6 不因所有受控 CPU fixture 通过而视为全业务目标验收。

- [ ] B3.1 定义 Core、shared runtime、YOLO、PatchCore、ONNX、DINOv2 和模型资源的 build target。
- [ ] B3.2 复用统一依赖锁和明确的文件所有权，模块不得重复打包 Python、Qt、Torch 或其他公共依赖。
- [x] B3.3 从构建输入自动生成模块 ID、版本、Core 范围、Python ABI、依赖锁 SHA、依赖模块、文件清单、大小和 SHA256。
- [ ] B3.4 生成模块 ZIP 和总索引；每个资产都独立校验。
- [ ] B3.5 对比 Core/模块压缩前后体积和重复文件，记录相对现有完整 ZIP 的真实节省。
- [ ] B3.6 所有目标在真实冻结程序中验证，不仅依赖构建配置单测。

### B4 — 新发布协议与兼容

> 实施注：protocol 4 独立布局、身份绑定、冷激活 lease 和原子 registry/恢复已有实现；协议 3 通道保留。B4.3 继续留空：没有 Core 升级或新 Core identity 的 registry 迁移。模块版本切换的有限证明不能关闭整条 Core 更新约束；B4.1 的完整行为资格还需 B5.6。

- [ ] B4.1 保持协议 3 的 manifest、delta、launcher 和 updater 行为不变。
- [x] B4.2 为模块化新安装定义显式新协议/schema，分离 Core 和模块 manifest。
- [ ] B4.3 Core 更新不得删除模块；模块更新不得覆盖 Core 或其他模块所有文件。
- [ ] B4.4 绑定应用 SHA、打包 SHA、Python ABI、依赖锁 SHA、模块索引 SHA 和 build identity。
- [ ] B4.5 模块更新前处理 Windows 已加载 DLL/.pyd 生命周期，必要时停止 worker 并重启。
- [ ] B4.6 支持失败回滚及模块注册表恢复。
- [ ] B4.7 首个模块化版本采用全新安装目录，不对协议 3 用户做原地布局转换。

### B5 — 联合离线验收

> 验收注：B5.1/B5.7 仅依据 run 45616400076 的新 Windows runner、独立 compiler/runtime venv、真实 x64 冻结与 12 个已逐成员验证的 ZIP；最大资产 1,865,186,577 字节，完整大小/哈希/build identity 在原报告中。该 run 的产品验收仍为 FAIL、cases 为空。B5.4 可在新的 EdgeSAM 不同版本/manifest 更新和 Core/全部无关模块哈希对照确实通过后记录限定 fixture 证明，目前不预勾。B5.2 的进程级网络禁止须准确标注，不能冒称目标机物理断网。B5.5 按实际执行的失败/恢复/卸载/重启范围记录，当前驱动没有安装中途终止或断电步骤，整条保留未完成；B5.6 仍需原协议原资产身份的 published retest。应用 b1201a03 已包含图片精简、CNN/DINO操作与YOLO的实际模块ID检查，区分资源准备、计算运行库、预训练与完整模型恢复；真实Qt生产控件的源码回归通过。新的Core诊断会通过实际项目导入与dataset builder观察WorkspaceView的YOLO/图片精简缺模块状态和Kaggle就绪性；结果仍待新EXE，且不覆盖CNN/DINO模型UI，不能提前勾选B5.3整句。B5.8 是持续发布边界，不代表 Release 已发布。

- [x] B5.1 从干净 Windows x64 环境构建完整 Core 和选定模块。
- [ ] B5.2 在无网络目标机安装 Core 和模块 ZIP。
- [ ] B5.3 验证模块缺失时 Core 正常启动、能力状态准确。
- [ ] B5.4 独立更新一个模块，证明 Core 和其他模块文件哈希不变。
- [ ] B5.5 验证中断/失败安装、恢复、卸载及重启。
- [ ] B5.6 运行现有协议 3 fixture/published update retest，确认旧用户路径未改变。
- [x] B5.7 每个资产小于 GitHub 单资产限制，并提供完整 size/hash/build identity 报告。
- [ ] B5.8 未经用户另行确认，不正式发布、不切换仓库可见性、不替换现有 Release。

## 4. 必须保留的测试和验收

- 保留 `tests/test_vision_train_runtime.py`、`tests/test_torch_runtime_hook.py`、`tests/test_build_collect_paths.py`、`tests/test_update_protocol_build.py` 等现有断言。
- 增加 CP312 运行时验证、DLL/ABI、模块 manifest 和离线事务的定向测试。
- 不删除失败用例，不降低覆盖率，不把 fixture 通过写成产品 GPU/GUI 验收。
- 真实 GPU 缺失时明确 NOT_RUN。
- 旧协议 3 的 published retest 仍以旧协议样本和原资产身份验证，不用新协议样本替代。

## 5. 跨仓库顺序

- B0 与应用 A0 并行。
- B1 等应用 A1 的依赖锁候选确定后实施。
- B2 与应用 A2/A3 联调，但 B2 必须使用同一应用/打包/锁 SHA。
- B3 等应用 A4 的模块目录和 manifest 合同冻结后实施。
- B4 与应用 A5/A6 联调。
- B5 最后执行。

原计划文档分支只提交计划文档，不改变产品配置、工作流、Hook、协议或发布资产；产品候选实现在上方注明的应用主分支和打包 PR #6 中。

